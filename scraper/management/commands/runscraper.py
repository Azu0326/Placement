"""Poll and execute queued scraper runs."""

from django.core.management.base import BaseCommand

from scraper.services.queue import process_one


class Command(BaseCommand):
    help = "Process queued scraper runs. Loop with --loop."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--interval", type=float, default=2)

    def handle(self, *args, **options):
        import time

        if not options["loop"]:
            processed = process_one()
            self.stdout.write("processed" if processed else "idle")
            return
        while True:
            process_one()
            time.sleep(options["interval"])
