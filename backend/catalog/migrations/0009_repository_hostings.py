from django.db import migrations, models

# The hostings that were fixed in the code until now.
HOSTINGS = [
    ('github', 'GitHub'), ('bitbucket', 'Bitbucket'), ('hostinger', 'Hostinger (deploy remote)'),
    ('local', 'Local only'),
]


def create_hostings(apps, schema_editor):
    RepositoryHosting = apps.get_model('catalog', 'RepositoryHosting')
    Repository = apps.get_model('catalog', 'Repository')
    for slug, name in HOSTINGS:
        RepositoryHosting.objects.create(slug=slug, name=name)
    # Anything else a repository holds gets a hosting too, so none is left without one.
    known = {slug for slug, _ in HOSTINGS}
    for slug in sorted(set(Repository.objects.values_list('hosting', flat=True)) - known - {''}):
        RepositoryHosting.objects.create(slug=slug, name=slug)


def drop_hostings(apps, schema_editor):
    apps.get_model('catalog', 'RepositoryHosting').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0008_platform_kinds'),
    ]

    operations = [
        migrations.CreateModel(
            name='RepositoryHosting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True)),
                ('slug', models.SlugField(max_length=60, unique=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AlterField(
            model_name='repository',
            name='hosting',
            field=models.CharField(default='local', max_length=60),
        ),
        migrations.RunPython(create_hostings, drop_hostings),
    ]
