from django.test import TestCase
from django.urls import reverse

from authentication.roles import ROLE_EDITOR, ROLE_VIEWER
from authentication.services.auth_service import BACKEND_PATH
from scraper.constants import EXPORT_CSV, EXPORT_READY
from scraper.models import ExportArtifact
from scraper.tests.helpers import make_job, make_user, queued_run


class PermissionTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner.user", ROLE_EDITOR)
        self.other = make_user("other.user", ROLE_EDITOR)
        self.viewer = make_user("viewer.user", ROLE_VIEWER)
        self.job = make_job(self.owner, name="Owned job", start_url="https://example.com/")
        self.run = queued_run(self.job, self.owner)
        self.export = ExportArtifact.objects.create(
            run=self.run,
            format=EXPORT_CSV,
            status=EXPORT_READY,
            file_name="x.csv",
            storage_name="missing.csv",
            requested_by=self.owner,
        )

    def test_anonymous_redirected(self):
        response = self.client.get(reverse("jobs"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_other_user_cannot_view_job(self):
        self.client.force_login(self.other, backend=BACKEND_PATH)
        self.assertEqual(self.client.get(reverse("job_detail", args=[self.job.id])).status_code, 404)

    def test_other_user_cannot_run_job(self):
        self.client.force_login(self.other, backend=BACKEND_PATH)
        response = self.client.post(reverse("api_start_run", args=[self.job.id]), content_type="application/json", data="{}")
        self.assertEqual(response.status_code, 404)

    def test_other_user_cannot_view_results(self):
        self.client.force_login(self.other, backend=BACKEND_PATH)
        self.assertEqual(
            self.client.get(reverse("run_records", args=[self.job.id, self.run.id])).status_code,
            404,
        )

    def test_other_user_cannot_download_export(self):
        self.client.force_login(self.other, backend=BACKEND_PATH)
        self.assertEqual(
            self.client.get(reverse("export_download", args=[self.job.id, self.run.id, self.export.id])).status_code,
            404,
        )

    def test_viewer_cannot_create_job(self):
        self.client.force_login(self.viewer, backend=BACKEND_PATH)
        self.assertEqual(self.client.get(reverse("job_new")).status_code, 403)

    def test_owner_can_view(self):
        self.client.force_login(self.owner, backend=BACKEND_PATH)
        self.assertEqual(self.client.get(reverse("job_detail", args=[self.job.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 200)
        self.assertEqual(self.client.get(reverse("execution")).status_code, 200)
