from django.db import migrations, models

# The categories that were fixed in the code until now.
CATEGORIES = [
    ('language', 'Language'), ('framework', 'Framework'), ('library', 'Library'), ('cms', 'CMS'),
    ('database', 'Database'), ('infra', 'Infrastructure'), ('other', 'Other'),
]


def create_categories(apps, schema_editor):
    TechnologyCategory = apps.get_model('catalog', 'TechnologyCategory')
    Technology = apps.get_model('catalog', 'Technology')
    for slug, name in CATEGORIES:
        TechnologyCategory.objects.create(slug=slug, name=name)
    # Anything else a technology holds gets a category too, so none is left without one.
    known = {slug for slug, _ in CATEGORIES}
    for slug in sorted(set(Technology.objects.values_list('category', flat=True)) - known - {''}):
        TechnologyCategory.objects.create(slug=slug, name=slug)


def drop_categories(apps, schema_editor):
    apps.get_model('catalog', 'TechnologyCategory').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0006_project_notes_markdown'),
    ]

    operations = [
        migrations.CreateModel(
            name='TechnologyCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True)),
                ('slug', models.SlugField(max_length=60, unique=True)),
            ],
            options={
                'ordering': ['name'],
                'verbose_name_plural': 'technology categories',
            },
        ),
        migrations.AlterField(
            model_name='technology',
            name='category',
            field=models.CharField(blank=True, default='', max_length=60),
        ),
        migrations.RunPython(create_categories, drop_categories),
    ]
