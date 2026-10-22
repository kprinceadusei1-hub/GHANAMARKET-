from django.urls import path

from . import views

app_name = "commerce"

urlpatterns = [
    path("cart/", views.cart, name="cart"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/items/<int:item_id>/update/", views.cart_update, name="cart_update"),
    path("cart/items/<int:item_id>/remove/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/<str:reference>/", views.checkout_pay, name="checkout_pay"),
    path("checkout/<str:reference>/cancel/", views.checkout_cancel, name="checkout_cancel"),
    path("payments/callback/", views.payment_callback, name="payment_callback"),
    path("payments/webhooks/<slug:provider_name>/", views.payment_webhook, name="payment_webhook"),
    path("payments/test/<str:reference>/", views.test_payment, name="test_payment"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<str:number>/", views.order_detail, name="order_detail"),
    path("orders/<str:number>/issue/", views.order_issue, name="order_issue"),
    path("seller/orders/", views.seller_orders, name="seller_orders"),
    path("seller/orders/<str:number>/", views.seller_order_detail, name="seller_order_detail"),
    path("account/addresses/", views.addresses, name="addresses"),
    path("account/addresses/<int:pk>/delete/", views.address_delete, name="address_delete"),
]
