from django.db import migrations


def require_review_for_existing_listings(apps, schema_editor):
    Product = apps.get_model("marketplace", "Product")
    Product.objects.filter(
        status="published",
        is_demo=False,
    ).update(
        status="pending",
        moderation_note="",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace", "0007_product_brand_product_included_items_product_model_and_more"),
    ]

    operations = [
        migrations.RunPython(
            require_review_for_existing_listings,
            migrations.RunPython.noop,
        ),
    ]
