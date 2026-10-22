from django.db import migrations


def seed(apps, schema_editor):
    from marketplace.category_catalog import seed_catalog

    Category = apps.get_model("marketplace", "Category")
    CategoryAttribute = apps.get_model("marketplace", "CategoryAttribute")
    seed_catalog(Category, CategoryAttribute)

    # Any listing whose stored category slug is unknown keeps working under "Other".
    Product = apps.get_model("marketplace", "Product")
    known = set(Category.objects.values_list("slug", flat=True))
    Product.objects.exclude(category__in=known).update(category="other")


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0010_category_categoryattribute'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
