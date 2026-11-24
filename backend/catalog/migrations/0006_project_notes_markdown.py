from django.db import migrations, models


class Migration(migrations.Migration):
    """Project notes can be Markdown. The existing ones were written as plain text, so they
    get False; new projects default to True."""

    dependencies = [
        ('catalog', '0005_project_groups'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='notes_markdown',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='project',
            name='notes_markdown',
            field=models.BooleanField(default=True),
        ),
    ]
