"""“Buy now” pays for one item only; the rest of the cart is left alone."""
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from marketplace.models import User

from . import services
from .models import CartItem, Order, Refund
from .tests import CommerceFixtures


class BuyNowTests(CommerceFixtures):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.buyer)

    def buy_now(self, product, quantity=1):
        return self.client.post(reverse("commerce:cart_add", args=[product.pk]),
                                {"quantity": quantity, "next": "checkout"})

    def test_buy_now_checks_out_only_that_item(self):
        services.add_to_cart(self.buyer, self.shoes, 2)
        response = self.buy_now(self.phone)
        checkout_url = f"{reverse('commerce:checkout')}?only={self.phone.pk}"
        self.assertRedirects(response, checkout_url)
        page = self.client.get(checkout_url)
        self.assertContains(page, "You are buying just this item")
        lines = [line["item"].product for group in page.context["groups"] for line in group["items"]]
        self.assertEqual(lines, [self.phone])

        response = self.client.post(checkout_url, {f"delivery_{self.seller.pk}": self.pickup.pk})
        checkout = self.buyer.checkouts.get()
        self.assertRedirects(response, reverse("commerce:checkout_pay", args=[checkout.reference]),
                             fetch_redirect_response=False)
        self.assertEqual(list(Order.objects.values_list("seller_id", flat=True)), [self.seller.pk])
        self.assertEqual(str(checkout.total), "1000.00")
        # The shoes are still in the cart, untouched; the phone line was used up.
        self.assertEqual(list(CartItem.objects.filter(user=self.buyer).values_list("product_id", "quantity")),
                         [(self.shoes.pk, 2)])

    def test_buy_now_sets_quantity_instead_of_adding(self):
        services.add_to_cart(self.buyer, self.phone, 2)
        self.buy_now(self.phone, 1)
        self.assertEqual(CartItem.objects.get(user=self.buyer, product=self.phone).quantity, 1)

    def test_whole_cart_checkout_still_takes_everything(self):
        services.add_to_cart(self.buyer, self.phone, 1)
        services.add_to_cart(self.buyer, self.shoes, 1)
        self.client.post(reverse("commerce:checkout"), {
            f"delivery_{self.seller.pk}": self.pickup.pk, f"delivery_{self.other_seller.pk}": self.pickup.pk,
        })
        self.assertEqual(Order.objects.count(), 2)
        self.assertFalse(CartItem.objects.filter(user=self.buyer).exists())

    def test_buy_now_for_an_item_not_in_cart_goes_back_to_cart(self):
        response = self.client.get(f"{reverse('commerce:checkout')}?only={self.shoes.pk}")
        self.assertRedirects(response, reverse("commerce:cart"))

    def test_buy_now_refusal_keeps_buyer_on_listing(self):
        self.client.force_login(self.seller)
        response = self.buy_now(self.phone)
        self.assertRedirects(response, reverse("product_detail", args=[self.phone.pk]))

    def test_checkout_names_the_shop(self):
        User.objects.filter(pk=self.seller.pk).update(store_name="Kofi Phones")
        services.add_to_cart(self.buyer, self.phone, 1)
        form = self.client.get(reverse("commerce:checkout")).context["form"]
        self.assertEqual(form.fields[f"delivery_{self.seller.pk}"].label, "Delivery for items from Kofi Phones")


class AdminQueueTests(CommerceFixtures):
    def test_failed_refunds_reach_the_admin_bell_and_sidebar(self):
        order = self.place_order().orders.get()
        Refund.objects.create(order=order, amount=order.total, status=Refund.Status.FAILED, reason="Provider error")
        finance = User.objects.create_user("cash", "cash@example.com", "A-strong-password-482!", is_staff=True)
        finance.user_permissions.add(*Permission.objects.filter(codename__in=("view_refund", "view_payment")))
        self.client.force_login(finance)
        response = self.client.get(reverse("admin:index"))
        queues = {queue["key"]: queue["count"] for queue in response.context["cc_queues"]}
        self.assertEqual(queues["failed_refunds"], 1)
        self.assertEqual(queues["payment_attention"], 0)
        refunds_link = next(link for group in response.context["cc_sidebar"] for link in group["links"]
                            if link["label"] == "Refunds")
        self.assertEqual(refunds_link["count"], 1)

    def test_queues_hidden_without_permission(self):
        staff = User.objects.create_user("help", "help@example.com", "A-strong-password-482!", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_supportrequest"))
        self.client.force_login(staff)
        keys = [queue["key"] for queue in self.client.get(reverse("admin:index")).context["cc_queues"]]
        self.assertEqual(keys, ["support"])

    def test_listing_admin_page_query_count_stays_flat(self):
        admin = User.objects.create_superuser("boss", "boss@example.com", "A-strong-password-482!")
        self.client.force_login(admin)
        url = reverse("admin:marketplace_product_change", args=[self.phone.pk])
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertLess(len(queries), 30)
