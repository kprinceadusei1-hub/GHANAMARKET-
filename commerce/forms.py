from django import forms

from marketplace.forms import TownFieldMixin
from marketplace.models import GhanaRegion

from .models import Address, DeliveryOption, Order, OrderIssue


class AddressForm(TownFieldMixin, forms.ModelForm):
    class Meta:
        model = Address
        fields = ("full_name", "phone_number", "region", "city", "street", "digital_address")
        widgets = {"phone_number": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["region"].choices = (("", "Choose a region"), *GhanaRegion.choices)
        self.fields["full_name"].widget.attrs["autocomplete"] = "name"


def delivery_label(option):
    fee = "Free" if not option.fee else f"GH₵ {option.fee:,.2f}"
    parts = [f"{option.name} — {fee}"]
    if option.estimated_days:
        parts.append(option.estimated_days)
    if option.description:
        parts.append(option.description)
    return " · ".join(parts)


class CheckoutForm(forms.Form):
    """Delivery choice per seller, plus a saved or new address when any choice needs one."""

    address = forms.ModelChoiceField(
        queryset=Address.objects.none(), required=False, empty_label=None, widget=forms.RadioSelect,
        label="Deliver to",
    )
    note = forms.CharField(
        required=False, max_length=500, label="Note for the seller",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Optional, e.g. best time to call"}),
    )

    def __init__(self, user, groups, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.groups = groups
        addresses = Address.objects.filter(user=user)
        self.fields["address"].queryset = addresses
        self.fields["address"].label_from_instance = lambda a: f"{a.full_name} · {a.phone_number} · {a.as_text()}"
        if addresses:
            self.fields["address"].initial = addresses[0]
        self.new_address_form = AddressForm(
            self.data if self.is_bound and not self.data.get("address") else None, prefix="new",
            initial={"full_name": user.get_full_name(), "phone_number": user.phone_number,
                     "region": user.region, "city": user.city},
        )
        options = DeliveryOption.objects.filter(is_active=True)
        for group in groups:
            name = self.delivery_field_name(group["seller"].pk)
            self.fields[name] = forms.ModelChoiceField(
                queryset=options, widget=forms.RadioSelect, empty_label=None,
                label=f"Delivery for items from {group['seller'].get_full_name() or group['seller'].username}",
                error_messages={"required": "Choose how you want to receive these items."},
            )
            self.fields[name].label_from_instance = delivery_label
            if options:
                self.fields[name].initial = options[0]
            group["delivery_field"] = self[name]

    @staticmethod
    def delivery_field_name(seller_id):
        return f"delivery_{seller_id}"

    def delivery_by_seller(self):
        return {group["seller"].pk: self.cleaned_data[self.delivery_field_name(group["seller"].pk)]
                for group in self.groups}

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        needs_address = any(option.requires_address for option in self.delivery_by_seller().values())
        if needs_address and not cleaned.get("address"):
            if not self.new_address_form.is_valid():
                raise forms.ValidationError("Add a delivery address, or choose collection from the seller.")
        return cleaned

    def resolve_address(self):
        """The chosen saved address, or a newly saved one, or None when everything is collected."""
        if self.cleaned_data.get("address"):
            return self.cleaned_data["address"]
        if any(option.requires_address for option in self.delivery_by_seller().values()):
            address = self.new_address_form.save(commit=False)
            address.user = self.user
            address.is_default = not Address.objects.filter(user=self.user).exists()
            address.save()
            return address
        return None


class OrderStatusForm(forms.Form):
    to_status = forms.ChoiceField(label="Update status")
    tracking_reference = forms.CharField(
        required=False, max_length=100, label="Tracking or rider reference",
        help_text="Optional. Shared with the buyer.",
    )
    note = forms.CharField(
        required=False, max_length=500, label="Message to the buyer",
        widget=forms.Textarea(attrs={"rows": 2}), help_text="Required when cancelling.",
    )

    def __init__(self, transitions, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(Order.Status.choices)
        ordering = [value for value, _ in Order.Status.choices]
        self.fields["to_status"].choices = [(s, labels[s]) for s in sorted(transitions, key=ordering.index)]


class OrderIssueForm(forms.ModelForm):
    class Meta:
        model = OrderIssue
        fields = ("kind", "reason", "details")
        labels = {"kind": "What do you need?", "reason": "Short reason", "details": "Details"}
        widgets = {
            "reason": forms.TextInput(attrs={"placeholder": "e.g. Item arrived damaged"}),
            "details": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, order, *args, **kwargs):
        super().__init__(*args, **kwargs)
        kinds = [OrderIssue.Kind.RETURN, OrderIssue.Kind.REFUND, OrderIssue.Kind.DISPUTE]
        if order.status in {Order.Status.PAID, Order.Status.PROCESSING}:
            kinds.insert(0, OrderIssue.Kind.CANCELLATION)
        self.fields["kind"].choices = [(k.value, k.label) for k in kinds]
