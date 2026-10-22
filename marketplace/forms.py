from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.utils.html import escape

from .images import normalise_upload

from .models import (
    Category, CategoryAttribute, GhanaRegion, ListingReport, Message, Product, ProductPhoto, SellerReview,
    SellerVerification, SupportRequest, User, UserReport,
)


MAX_PRODUCT_PHOTOS = 8
MAX_PRODUCT_IMAGE_SIZE = 5 * 1024 * 1024


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        if len(files) > MAX_PRODUCT_PHOTOS:
            raise ValidationError(
                f"Upload no more than {MAX_PRODUCT_PHOTOS} photos at a time."
            )
        cleaned_files = []
        for file in files:
            if file.size > MAX_PRODUCT_IMAGE_SIZE:
                raise ValidationError(
                    "Each photo must be 5 MB or smaller. Please resize the image and try again."
                )
            cleaned = super().clean(file, initial)
            try:
                cleaned_files.append(normalise_upload(cleaned))
            except (OSError, ValueError) as exc:
                raise ValidationError("Upload a valid image. The file you uploaded was not an image or is damaged.") from exc
        return cleaned_files


class RegistrationForm(UserCreationForm):
    country = forms.RegexField(
        regex=r"^[A-Za-z]{2}$",
        error_messages={"invalid": "Enter a two-letter country code."},
    )

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "phone_number",
            "city",
            "region",
            "country",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["country"].initial = "GH"
        self.fields["region"].choices = (
            ("", "Choose a region"),
            *GhanaRegion.choices,
        )
        self.fields["region"].help_text = "Optional. Select your Ghana region."

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_country(self):
        return self.cleaned_data["country"].upper()

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("role") == User.Role.SELLER:
            for field in ("phone_number", "city", "region"):
                if not cleaned_data.get(field):
                    self.add_error(field, "Required for seller accounts.")
        return cleaned_data


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone_number", "city", "region")
        labels = {"phone_number": "Phone number", "city": "City or town"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["region"].choices = (("", "Choose a region"), *GhanaRegion.choices)
        self.fields["region"].required = False

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.role == User.Role.SELLER:
            for field in ("phone_number", "city", "region"):
                if not cleaned_data.get(field):
                    self.add_error(field, "Required for seller accounts.")
        return cleaned_data


class SellerUpgradeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("phone_number", "city", "region")
        labels = {"phone_number": "Phone number", "city": "City or town"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["region"].choices = (("", "Choose a region"), *GhanaRegion.choices)
        for field in self.fields.values():
            field.required = True


class ProductForm(forms.ModelForm):
    images = MultipleImageField(
        required=False,
        label="Item photos",
        help_text="Upload up to 8 clear photos (5 MB each) showing different sides and details of the item.",
    )
    region = forms.ChoiceField(
        choices=(("", "Choose a region"), *GhanaRegion.choices),
        label="Region",
    )
    price_negotiable = forms.BooleanField(
        required=False,
        label="Price is negotiable",
        help_text="Tick this if you are open to reasonable offers.",
    )

    class Meta:
        model = Product
        fields = (
            "title",
            "category",
            "subcategory",
            "brand",
            "model",
            "condition",
            "price",
            "price_negotiable",
            "allows_direct_contact",
            "allows_checkout",
            "stock_quantity",
            "included_items",
            "description",
            "region",
            "city",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "included_items": forms.TextInput(
                attrs={"placeholder": "e.g. charger, case, receipt"}
            ),
            "price": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }

    ATTRIBUTE_PREFIX = "attr_"

    def __init__(self, *args, category=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(parent__isnull=True, is_active=True)
        self.fields["category"].empty_label = "Choose a category"
        self.selected_category = self._resolve_category(category)
        subcategories = (
            self.selected_category.children.filter(is_active=True) if self.selected_category else Category.objects.none()
        )
        self.fields["subcategory"].queryset = subcategories
        self.fields["subcategory"].label_from_instance = lambda category: category.name
        self.fields["subcategory"].empty_label = "Choose a subcategory"
        self.fields["subcategory"].required = False
        if not subcategories.exists():
            self.fields["subcategory"].widget = forms.HiddenInput()
        if self.selected_category and self.selected_category.price_label:
            self.fields["price"].label = f"{self.selected_category.price_label} (GH₵)"
        else:
            self.fields["price"].label = "Price (GH₵)"
        self.attribute_definitions = []
        self._add_attribute_fields()
        self.fields["allows_direct_contact"].label = "Buyers can message me"
        self.fields["allows_direct_contact"].help_text = "Chat privately inside GhanaMarket. Your phone number stays hidden."
        self.fields["allows_checkout"].label = "Sell online with checkout"
        self.fields["allows_checkout"].help_text = (
            "Buyers pay online (Mobile Money or card) and you fulfil the order. Requires stock below."
        )
        self.fields["stock_quantity"].label = "Units available"
        self.fields["stock_quantity"].required = False
        self.fields["stock_quantity"].widget.attrs.update({"min": 0, "inputmode": "numeric"})
        if self.selected_category and not self.selected_category.allows_checkout:
            self.fields["allows_checkout"].disabled = True
            self.fields["allows_checkout"].initial = False
            self.fields["allows_checkout"].help_text = (
                f"Online checkout is not available for {self.selected_category.name}. Buyers will contact you."
            )
        self.fields["region"].required = True
        self.fields["region"].help_text = "Choose where this listing is located."
        self.fields["images"].widget.attrs["accept"] = "image/*"
        self.fields["title"].help_text = "Use a clear title buyers can search for."
        self.fields["description"].help_text = (
            "Describe the item honestly: its features, defects, age, and anything "
            "buyers should know."
        )
        self.fields["brand"].required = False
        self.fields["brand"].help_text = "Optional. Add the brand when relevant."
        self.fields["model"].required = False
        self.fields["model"].help_text = "Optional. Add the model or version when known."
        self.fields["included_items"].label = "What is included?"
        self.fields["included_items"].help_text = (
            "Optional. List accessories or parts included with the item."
        )

    def _resolve_category(self, category):
        slug = self.data.get(self.add_prefix("category")) if self.is_bound else None
        if not slug and category is not None:
            return category
        if not slug and self.instance.pk:
            return self.instance.category
        if not slug:
            slug = self.initial.get("category")
        return Category.objects.filter(parent__isnull=True, is_active=True, slug=slug).first() if slug else None

    def _add_attribute_fields(self):
        if not self.selected_category:
            return
        existing = self.instance.attributes or {}
        for definition in self.selected_category.attribute_definitions():
            name = self.ATTRIBUTE_PREFIX + definition.key
            options = {
                "label": definition.label + (f" ({definition.unit})" if definition.unit else ""),
                "required": definition.is_required,
                # Admin-entered text: escape it, because the field template renders help text as HTML.
                "help_text": escape(definition.help_text),
                "initial": existing.get(definition.key),
            }
            if definition.kind == CategoryAttribute.Kind.NUMBER:
                field = forms.DecimalField(min_value=0, max_digits=14, decimal_places=2, **options)
            elif definition.kind == CategoryAttribute.Kind.CHOICE:
                field = forms.ChoiceField(choices=[("", "Choose…"), *[(c, c) for c in definition.choice_list]], **options)
            elif definition.kind == CategoryAttribute.Kind.BOOLEAN:
                options["required"] = False
                field = forms.BooleanField(**options)
            else:
                field = forms.CharField(max_length=100, **options)
            self.fields[name] = field
            self.attribute_definitions.append(definition)

    def attribute_fields(self):
        return [self[self.ATTRIBUTE_PREFIX + definition.key] for definition in self.attribute_definitions]

    def clean(self):
        cleaned_data = super().clean()
        category, subcategory = cleaned_data.get("category"), cleaned_data.get("subcategory")
        if category and subcategory and subcategory.parent_id != category.pk:
            self.add_error("subcategory", "Choose a subcategory that belongs to the selected category.")
        attributes = {}
        for definition in self.attribute_definitions:
            value = cleaned_data.get(self.ATTRIBUTE_PREFIX + definition.key)
            if value in (None, ""):
                continue
            if definition.kind == CategoryAttribute.Kind.NUMBER:
                value = int(value) if value == value.to_integral_value() else float(value)
            attributes[definition.key] = value
        cleaned_data["attributes"] = attributes
        from .trust import blocked_listing_reason

        reason = blocked_listing_reason(
            cleaned_data.get("title", ""), cleaned_data.get("description", ""),
            cleaned_data.get("brand", ""), cleaned_data.get("model", ""),
        )
        if reason:
            raise ValidationError(reason)
        if category and not category.allows_checkout:
            cleaned_data["allows_checkout"] = False
        if not cleaned_data.get("allows_checkout") and not cleaned_data.get("allows_direct_contact"):
            # A listing must be reachable somehow; messaging was the original (and default) method.
            cleaned_data["allows_direct_contact"] = True
        if cleaned_data.get("stock_quantity") is None:
            cleaned_data["stock_quantity"] = self.instance.stock_quantity if self.instance.pk else 1
        if cleaned_data.get("allows_checkout") and not cleaned_data.get("stock_quantity"):
            self.add_error("stock_quantity", "Add at least one unit to sell online.")
        uploaded_images = cleaned_data.get("images", [])
        existing_count = 0
        if self.instance and self.instance.pk:
            existing_count = self.instance.photos.count()
            if self.instance.image:
                existing_count += 1
        if existing_count + len(uploaded_images) > MAX_PRODUCT_PHOTOS:
            self.add_error(
                "images",
                f"This listing can have no more than {MAX_PRODUCT_PHOTOS} photos total.",
            )
        if not existing_count and not uploaded_images:
            self.add_error("images", "Upload at least one photo of the item.")
        return cleaned_data

    def save(self, commit=True):
        self.instance.attributes = self.cleaned_data.get("attributes", {})
        return super().save(commit=commit)


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ("body",)
        labels = {"body": "Message"}
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": 2000,
                    "placeholder": "Ask the seller about this listing...",
                }
            ),
        }


class ListingReportForm(forms.ModelForm):
    class Meta:
        model = ListingReport
        fields = ("reason", "details")
        labels = {"details": "Additional details (optional)"}
        widgets = {
            "details": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": 1000,
                    "placeholder": "Tell the admin what concerned you...",
                }
            ),
        }


MAX_DOCUMENT_SIZE = 5 * 1024 * 1024
DOCUMENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}


class SellerVerificationForm(forms.ModelForm):
    confirm = forms.BooleanField(
        label="I confirm these details are mine (or my business's) and are accurate.",
        error_messages={"required": "Please confirm the details are accurate."},
    )

    class Meta:
        model = SellerVerification
        fields = ("kind", "legal_name", "document_number", "business_name", "document")
        labels = {"kind": "What are you verifying?", "document": "Photo or scan of the document"}
        help_texts = {
            "business_name": "Only for registered businesses.",
            "document": "PDF, JPG or PNG, up to 5 MB. Only GhanaMarket staff can see it.",
        }

    def clean_document(self):
        document = self.cleaned_data["document"]
        if document.size > MAX_DOCUMENT_SIZE:
            raise ValidationError("The document must be 5 MB or smaller.")
        content_type = getattr(document, "content_type", "")
        if content_type not in DOCUMENT_TYPES:
            raise ValidationError("Upload a PDF, JPG or PNG file.")
        header = document.read(8)
        document.seek(0)
        signatures = (b"%PDF", b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")  # PDF, JPEG, PNG, WebP
        if not header.startswith(signatures):
            raise ValidationError("The file does not look like a PDF or image.")
        return document

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == SellerVerification.Kind.BUSINESS and not cleaned.get("business_name"):
            self.add_error("business_name", "Enter the registered business name.")
        return cleaned


class SellerReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        coerce=int, choices=[(n, f"{n} star{'s' if n > 1 else ''}") for n in range(5, 0, -1)],
        widget=forms.RadioSelect, label="Your rating",
    )

    class Meta:
        model = SellerReview
        fields = ("rating", "comment")
        labels = {"comment": "What went well or badly? (optional)"}
        widgets = {"comment": forms.Textarea(attrs={"rows": 3, "maxlength": 500})}


class UserReportForm(forms.ModelForm):
    class Meta:
        model = UserReport
        fields = ("reason", "details")
        labels = {"details": "What happened? (optional)"}
        widgets = {"details": forms.Textarea(attrs={"rows": 3, "maxlength": 1000})}


class SupportRequestForm(forms.ModelForm):
    class Meta:
        model = SupportRequest
        fields = ("email", "topic", "subject", "reference", "message")
        labels = {"email": "Your email", "topic": "What is this about?", "reference": "Order number or listing link (optional)"}
        widgets = {"message": forms.Textarea(attrs={"rows": 5, "maxlength": 3000})}


class AccountDeletionForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
                               label="Enter your password to confirm")

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise ValidationError("That password is not correct.")
        return password
