"""Create, list, reply to or delete Instagram comments.

Uses the Page access token and INSTAGRAM_ACCOUNT_ID. Tokens are never printed.

    python manage.py instagram_comment media
    python manage.py instagram_comment list --media-id 1789…
    python manage.py instagram_comment create --media-id 1789… --message "Test comment"
    python manage.py instagram_comment reply --comment-id 1790… --message "Thanks"
    python manage.py instagram_comment delete --comment-id 1790…
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from poster.exceptions import FacebookPublishError, InstagramNotConfigured
from poster.services.instagram_comments import InstagramCommentService


class Command(BaseCommand):
    help = "Create, read, reply to or delete Instagram comments on owned media."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=("media", "list", "create", "reply", "delete"),
            help="media = list recent posts; list/create need --media-id; reply/delete need --comment-id.",
        )
        parser.add_argument("--media-id", default="", help="IG Media id (from `media`).")
        parser.add_argument("--comment-id", default="", help="IG Comment id (from `list`).")
        parser.add_argument("--message", default="", help="Comment or reply text.")
        parser.add_argument("--limit", type=int, default=10, help="How many media items to list.")

    def handle(self, *args, **options):
        action = options["action"]
        service = InstagramCommentService()
        try:
            if action == "media":
                self._media(service, options["limit"])
            elif action == "list":
                self._list(service, options["media_id"])
            elif action == "create":
                comment = service.create_comment(options["media_id"], options["message"])
                self.stdout.write(self.style.SUCCESS(f"Created comment {comment.comment_id}"))
            elif action == "reply":
                comment = service.reply_to_comment(options["comment_id"], options["message"])
                self.stdout.write(self.style.SUCCESS(f"Replied {comment.comment_id}"))
            else:
                service.delete_comment(options["comment_id"])
                self.stdout.write(self.style.SUCCESS("Deleted comment"))
        except InstagramNotConfigured as exc:
            raise CommandError(str(exc)) from exc
        except FacebookPublishError as exc:
            raise CommandError(str(exc)) from exc

    def _media(self, service: InstagramCommentService, limit: int) -> None:
        items = service.list_media(limit=limit)
        if not items:
            self.stdout.write("No media. Publish a post on the Instagram account first.")
            return
        for item in items:
            caption = (item.caption or "").replace("\n", " ")[:80]
            self.stdout.write(f"{item.media_id}  {item.media_type}  {caption}")

    def _list(self, service: InstagramCommentService, media_id: str) -> None:
        comments = service.list_comments(media_id)
        if not comments:
            self.stdout.write("No comments on that media.")
            return
        for comment in comments:
            text = (comment.text or "").replace("\n", " ")[:120]
            who = comment.username or "—"
            self.stdout.write(f"{comment.comment_id}  @{who}  {text}")
