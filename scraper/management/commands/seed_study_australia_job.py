from django.core.management.base import BaseCommand, CommandError

from authentication.models import ScraposUser
from scraper.example import STUDY_AUSTRALIA_JOB
from scraper.services.jobs import apply_step, create_draft, replace_fields, replace_variables


class Command(BaseCommand):
    help = "Create the documented Study Australia scholarships scraper for a user."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        try:
            user = ScraposUser.objects.get(username=options["username"])
        except ScraposUser.DoesNotExist as exc:
            raise CommandError("No such user.") from exc
        job = create_draft(user, name=STUDY_AUSTRALIA_JOB["name"])
        apply_step(job, "source", STUDY_AUSTRALIA_JOB, user)
        apply_step(job, "results", STUDY_AUSTRALIA_JOB, user)
        apply_step(job, "pagination", STUDY_AUSTRALIA_JOB, user)
        replace_variables(job, STUDY_AUSTRALIA_JOB["variables"])
        replace_fields(job, STUDY_AUSTRALIA_JOB["fields"])
        self.stdout.write(self.style.SUCCESS(f"Created job {job.id}"))
