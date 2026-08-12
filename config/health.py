"""
ALB/ECS liveness for Scrapos.

Served from middleware so /healthz answers before CommonMiddleware validates
Host. The ALB probes by private IP:port, which is not in ALLOWED_HOSTS.
"""

import json
import os

from django.http import HttpResponse, JsonResponse

HEALTHZ_PATHS = frozenset({"/healthz", "/healthz/"})


def _payload():
    return {
        "status": "ok",
        "service": os.environ.get("SERVICE_NAME", "scrapos"),
    }


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in HEALTHZ_PATHS:
            return HttpResponse(
                json.dumps(_payload()),
                content_type="application/json",
                headers={"Cache-Control": "no-store"},
            )
        return self.get_response(request)


def healthz(_request):
    response = JsonResponse(_payload())
    response["Cache-Control"] = "no-store"
    return response
