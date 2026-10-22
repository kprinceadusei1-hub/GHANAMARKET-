import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0009_favorite'),
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80)),
                ('slug', models.SlugField(max_length=60, unique=True)),
                ('icon', models.SlugField(blank=True, help_text='Icon key used by the site templates, e.g. vehicles, property. Defaults to the top-level slug.', max_length=40)),
                ('description', models.CharField(blank=True, max_length=200)),
                ('price_label', models.CharField(blank=True, help_text="Optional price label, e.g. 'Monthly rent' or 'Salary per month'.", max_length=40)),
                ('allows_checkout', models.BooleanField(default=True, help_text='Whether sellers may enable online checkout for listings in this category.')),
                ('is_restricted', models.BooleanField(default=False, help_text='Regulated category: listings get extra admin scrutiny and show the restriction note.')),
                ('restriction_note', models.CharField(blank=True, max_length=300)),
                ('position', models.PositiveSmallIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('parent', models.ForeignKey(blank=True, limit_choices_to={'parent__isnull': True}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='marketplace.category')),
            ],
            options={
                'verbose_name_plural': 'categories',
                'ordering': ('position', 'name'),
            },
        ),
        migrations.CreateModel(
            name='CategoryAttribute',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.SlugField(help_text='Storage key, e.g. year. Do not change once listings use it.', max_length=40)),
                ('label', models.CharField(max_length=60)),
                ('kind', models.CharField(choices=[('text', 'Text'), ('number', 'Number'), ('choice', 'Choice from a list'), ('boolean', 'Yes / no')], default='text', max_length=10)),
                ('choices', models.TextField(blank=True, help_text="For 'choice' attributes: one option per line.")),
                ('unit', models.CharField(blank=True, help_text='Optional unit shown after numbers, e.g. km.', max_length=20)),
                ('help_text', models.CharField(blank=True, max_length=150)),
                ('is_required', models.BooleanField(default=False)),
                ('is_filterable', models.BooleanField(default=True, help_text='Show as a filter when browsing this category.')),
                ('position', models.PositiveSmallIntegerField(default=0)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attributes', to='marketplace.category')),
            ],
            options={
                'ordering': ('position', 'label'),
                'constraints': [models.UniqueConstraint(fields=('category', 'key'), name='unique_category_attribute_key')],
            },
        ),
    ]
