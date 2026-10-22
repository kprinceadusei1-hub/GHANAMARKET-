import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0011_seed_categories'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='category',
            field=models.ForeignKey(db_column='category', limit_choices_to={'parent__isnull': True}, on_delete=django.db.models.deletion.PROTECT, related_name='products', to='marketplace.category', to_field='slug'),
        ),
        migrations.AddField(
            model_name='product',
            name='subcategory',
            field=models.ForeignKey(blank=True, limit_choices_to={'parent__isnull': False}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='subcategory_products', to='marketplace.category'),
        ),
        migrations.AddField(
            model_name='product',
            name='attributes',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['status', 'is_demo', '-created_at'], name='product_public_recent_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['category', 'status'], name='product_category_status_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['region', 'status'], name='product_region_status_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['price'], name='product_price_idx'),
        ),
    ]
