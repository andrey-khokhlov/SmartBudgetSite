from contextlib import ExitStack
from email import policy
from email.parser import HeaderParser
from ipaddress import ip_address, ip_network
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
import yaml

from app import main
from app.api.v1.perimeter import PERIMETER_AUTH_PATH
from app.core.config import Settings
from app.dependencies import require_admin

ROOT = Path(__file__).resolve().parents[1]
CADDY_CONFIG = ROOT / "deploy/Caddyfile.prod"
CADDY_CONFIG_IN_CONTAINER = "/etc/caddy/Caddyfile"
TEST_ALLOWLIST = "127.0.0.1/32"
uses_cached_caddy = pytest.mark.skipif(
    os.environ.get("SMARTBUDGET_TEST_CADDY") != "1",
    reason="set SMARTBUDGET_TEST_CADDY=1 to use the cached production Caddy image",
)


def test_production_proxy_reserves_caddy_address() -> None:
    compose_path = ROOT / "compose.prod.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    (proxy_ipam,) = compose["networks"]["proxy"]["ipam"]["config"]
    subnet = ip_network(proxy_ipam["subnet"])
    dynamic_range = ip_network(proxy_ipam["ip_range"])
    services = compose["services"]
    caddy_ip = ip_address(services["caddy"]["networks"]["proxy"]["ipv4_address"])

    assert dynamic_range.subnet_of(subnet)
    assert caddy_ip in subnet
    assert caddy_ip not in dynamic_range
    assert str(caddy_ip) == services["app"]["environment"]["SMARTBUDGET_CADDY_PEER"]


def uses_admin_dependency(dependant) -> bool:
    return dependant.call is require_admin or any(
        uses_admin_dependency(child) for child in dependant.dependencies
    )


def test_production_trusted_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTBUDGET_HOST", "WWW.Example.TEST")
    monkeypatch.setattr(
        main,
        "settings",
        Settings(
            _env_file=None,
            APP_ENV="prod",
            ADMIN_TOKEN="test-admin-token",
            SECRET_KEY="test-secret-key",
            RATE_LIMIT_ENABLED=True,
        ),
    )

    with TestClient(main.create_app(), follow_redirects=False) as client:
        assert client.get("https://www.example.test/v1/health").status_code == 200
        assert client.get("http://127.0.0.1:4000/v1/health").status_code == 200
        for host in ("example.test", "other.example.test", "localhost", "testserver"):
            assert client.get("/v1/health", headers={"Host": host}).status_code == 400

        rejected = client.get("/download/probe")
        assert rejected.status_code == 400
        assert rejected.headers["Referrer-Policy"] == "no-referrer"
        assert "no-store" in rejected.headers["Cache-Control"]


@pytest.mark.parametrize("app_env", ["dev", "test"])
def test_non_production_accepts_test_client_host(monkeypatch, app_env) -> None:
    monkeypatch.setattr(main.settings, "APP_ENV", app_env)

    with TestClient(main.create_app()) as client:
        assert client.get("/v1/health").status_code == 200
        assert client.get(PERIMETER_AUTH_PATH).status_code == 404


def caddy_container(*, allowlist: str | None, config: Path = CADDY_CONFIG) -> list[str]:
    service = yaml.safe_load((ROOT / "compose.prod.yml").read_text(encoding="utf-8"))[
        "services"
    ]["caddy"]
    executable, flags, script, shell_name = service["entrypoint"]
    env = ["--env=SMARTBUDGET_HOST=localhost"]
    if allowlist is not None:
        env.append(f"--env=SMARTBUDGET_ALLOWED_IP={allowlist}")
    return [
        *env,
        "--mount",
        f"type=bind,source={config},target={CADDY_CONFIG_IN_CONTAINER},readonly",
        f"--entrypoint={executable}",
        service["image"],
        flags,
        script.replace("$$", "$"),  # Compose unescapes dollars before executing.
        shell_name,
    ]


@uses_cached_caddy
def test_private_compose_renders_without_allowlist(tmp_path: Path) -> None:
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        "SMARTBUDGET_HOST=smartbudget.example.invalid\n"
        "SMARTBUDGET_APP_ENV_FILE=.env.production.app.example\n"
        "POSTGRES_USER=smartbudget_bootstrap\n"
        "POSTGRES_PASSWORD=local-config-check-only\n"
        "POSTGRES_DB=smartbudget\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("COMPOSE_PROFILES", None)
    env.pop("SMARTBUDGET_ALLOWED_IP", None)
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            "compose.prod.yml",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert set(services) == {"app", "db"}
    for service in services.values():
        assert "SMARTBUDGET_ALLOWED_IP" not in service["environment"]
        assert not service.get("ports")


@uses_cached_caddy
@pytest.mark.parametrize(
    "allowlist",
    [
        None,
        "",
        "127.0.0.256/32",
        "127.0.00.1/32",
        "127.0.0.1",
        "::1/128",
        "127.0.0.0/8",
        "127.0.0.1/32 127.0.0.2/32",
        "127.0.0.1/32,127.0.0.2/32",
        "127.0.0.1/32\n127.0.0.2/32",
    ],
)
def test_caddy_refuses_to_start_with_invalid_allowlist(allowlist: str | None) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            *caddy_container(allowlist=allowlist),
            "run",
            "--config",
            CADDY_CONFIG_IN_CONTAINER,
            "--adapter",
            "caddyfile",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert result.stderr.strip() == "SMARTBUDGET_ALLOWED_IP must be one IPv4 /32 CIDR."


@uses_cached_caddy
def test_caddy_adapts_and_validates_one_ipv4_host() -> None:
    adapted = docker(
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        *caddy_container(allowlist="192.0.2.10/32"),
        "adapt",
        "--config",
        CADDY_CONFIG_IN_CONTAINER,
        "--adapter",
        "caddyfile",
        "--validate",
    )
    assert json.loads(adapted)["apps"]["http"]["servers"]


@uses_cached_caddy
def test_caddy_security_headers_and_perimeter_routing(tmp_path: Path) -> None:
    test_config = tmp_path / "Caddyfile"
    # Caddy uses internal TLS for localhost. Keep the production site block intact.
    test_config.write_text(
        CADDY_CONFIG.read_text(encoding="utf-8") + """
http://:4000 {
    @trusted {
        path /_internal/perimeter/check
        method GET
        host localhost
        header X-Forwarded-For 127.0.0.1
        header X-Forwarded-Proto https
        not {
            header X-Forwarded-Uri *
        }
        not {
            header Cookie *
        }
        not {
            query debug_probe=*
        }
    }
    handle @trusted {
        @allow header X-Forwarded-Perimeter-Policy download_get
        @capability header_regexp X-Forwarded-Perimeter-Policy ^(download_post|consultation_booking)$
        @unavailable header X-Forwarded-Perimeter-Policy admin
        header @capability Referrer-Policy no-referrer
        header Retry-After 2
        header X-Test-Policy {header.X-Forwarded-Perimeter-Policy}
        respond @allow 204
        respond @unavailable 503
        respond 429
    }
    handle /_internal/perimeter/check {
        respond 503
    }
    handle {
        header /download/probe Referrer-Policy no-referrer
        redir /download/probe /v1/health 302
        respond 200
    }
}
""",
        encoding="utf-8",
    )
    probes = [
        ("GET", "/v1/health", "200", None),
        ("GET", "/", "200", None),
        ("GET", "/static/site.css", "200", None),
        ("GET", "/administer", "200", None),
        ("GET", "/products/1", "200", None),
        ("POST", "/products/1/releases", "200", None),
        ("POST", "/v1/webhooks/resend", "200", None),
        ("GET", "/download/probe?debug_probe=private", "302", None),
        ("GET", "/_internal/perimeter/check", "404", None),
        ("POST", "/v1/feedback/", "429", "feedback"),
        ("POST", "/v1/check-purchase", "429", "purchase_lookup"),
        ("POST", "/download/probe?debug_probe=private", "429", "download_post"),
        ("GET", "/consultation/book/probe", "429", "consultation_booking"),
        ("POST", "/admin/login", "429", "admin_login"),
        ("GET", "/admin/login", "503", "admin"),
        ("POST", "/v1/webhooks/calendly", "429", "calendly"),
        ("POST", "/v1/webhooks/lava-top/payment-result", "429", "lava_top"),
    ]
    for route in main.app.routes:
        if isinstance(route, APIRoute) and uses_admin_dependency(route.dependant):
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            probes.extend((method, path, "503", "admin") for method in route.methods)
    denied_probes = [(method, path) for method, path, _, _ in probes] + [
        ("POST", "/checkout/probe"),
        ("POST", "/consultations/checkout/1"),
        ("GET", "/payment/result?probe=synthetic"),
    ]
    requests: list[str] = []
    for method, path, _, _ in probes:
        requests.extend(
            ("127.0.0.1", "198.51.100.1", method, "https://localhost" + path)
        )
    for method, path in denied_probes:
        requests.extend(("127.0.0.2", "127.0.0.1", method, "https://localhost" + path))
    requests.extend(("127.0.0.2", "127.0.0.1", "GET", "http://localhost/v1/health"))
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--add-host=app:127.0.0.1",
            "--env=SMARTBUDGET_HOST=localhost",
            f"--env=SMARTBUDGET_ALLOWED_IP={TEST_ALLOWLIST}",
            "--mount",
            f"type=bind,source={test_config},target=/etc/caddy/Caddyfile,readonly",
            "--entrypoint=sh",
            "caddy:2.11-alpine",
            "-ec",
            """
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >&2 &
curl -4 --retry 5 --retry-connrefused --retry-delay 1 --max-time 5 \\
    --silent --show-error --insecure --output /dev/null https://localhost/v1/health
while [ "$#" -gt 0 ]; do
    curl -4 --interface "$1" --max-time 5 --silent --show-error --insecure --dump-header - \\
        --output /dev/null -X "$3" -H "X-Forwarded-For: $2" \\
        -H "Forwarded: for=$2;proto=https" -H "X-Real-IP: $2" \\
        -H 'X-Forwarded-Proto: http' \\
        -H 'X-Forwarded-Perimeter-Policy: unknown' -H 'Cookie: synthetic=value' "$4"
    shift 4
done
""",
            "test-caddy",
            *requests,
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    *responses, redirect = result.stdout.strip().split("\n\n")
    parser = HeaderParser(policy=policy.HTTP)
    assert len(responses) == len(probes) + len(denied_probes)
    for block, (_, path, expected_status, expected_policy) in zip(
        responses[: len(probes)], probes, strict=True
    ):
        status, _, fields = block.partition("\n")
        assert status.split()[1] == expected_status, (path, block)
        headers = parser.parsestr(fields)
        assert headers["X-Test-Policy"] == expected_policy
        if expected_status == "429":
            assert headers["Retry-After"] == "2"
        expected_referrer = (
            "no-referrer"
            if path.startswith(("/download/", "/consultation/book/"))
            else "strict-origin-when-cross-origin"
        )
        assert headers.get_all("Referrer-Policy") == [expected_referrer]
        assert headers.get_all("X-Content-Type-Options") == ["nosniff"]
        assert headers.get_all("X-Frame-Options") == ["DENY"]
        assert headers.get_all("Strict-Transport-Security") == ["max-age=31536000"]

    for block, (_, path) in zip(responses[len(probes) :], denied_probes, strict=True):
        status, _, fields = block.partition("\n")
        assert status.split()[1] == "403", (path, block)
        headers = parser.parsestr(fields)
        assert "X-Test-Policy" not in headers
        assert headers.get_all("X-Content-Type-Options") == ["nosniff"]
        assert headers.get_all("X-Frame-Options") == ["DENY"]
        assert headers.get_all("Strict-Transport-Security") == ["max-age=31536000"]
        if path.startswith(("/download/", "/consultation/book/")):
            assert headers.get_all("Cache-Control") == ["private, no-store, max-age=0"]
            assert headers.get_all("Pragma") == ["no-cache"]
            assert headers.get_all("Expires") == ["0"]
            assert headers.get_all("Referrer-Policy") == ["no-referrer"]
        elif path.startswith("/payment/result"):
            assert headers.get_all("Cache-Control") == ["no-store"]
            assert headers.get_all("Referrer-Policy") == ["no-referrer"]
        else:
            assert headers.get_all("Referrer-Policy") == [
                "strict-origin-when-cross-origin"
            ]

    status, _, fields = redirect.partition("\n")
    assert status.split()[1] == "308"
    headers = parser.parsestr(fields)
    assert headers["Location"] == "https://localhost/v1/health"
    assert "Strict-Transport-Security" not in headers


def docker(*arguments: str) -> str:
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=40
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    return result.stdout.strip()


@pytest.mark.skipif(
    os.environ.get("SMARTBUDGET_TEST_CADDY") != "1"
    or not os.environ.get("SMARTBUDGET_TEST_APP_IMAGE"),
    reason="enable Caddy and set SMARTBUDGET_TEST_APP_IMAGE to a cached app image",
)
def test_caddy_and_uvicorn_enforce_the_production_proxy_boundary(
    tmp_path: Path,
) -> None:
    root = ROOT
    compose = yaml.safe_load((root / "compose.prod.yml").read_text(encoding="utf-8"))
    command = compose["services"]["app"]["command"]
    probe_file = tmp_path / "perimeter_probe.py"
    probe_file.write_text(
        """
from fastapi import Request
from app.main import app
from app.core.perimeter_rate_limiting import PerimeterRateLimiter
from app.core.rate_limiting import RollingWindowRateLimiter


def clock():
    return 100.0


app.state.perimeter_rate_limiter = PerimeterRateLimiter(max_buckets=10_000, clock=clock)
app.state.rate_limiter = RollingWindowRateLimiter(max_identities=10_000, clock=clock)


@app.get('/__test_proxy')
def proxy_probe(request: Request):
    return {
        'client': request.client.host,
        'peer': request.state.trusted_proxy_peer,
        'scheme': request.url.scheme,
    }
""",
        encoding="utf-8",
    )
    command[command.index("app.main:app")] = "perimeter_probe:app"
    network = f"smartbudget-sec012-{uuid4().hex}"
    caddy = network + "-caddy"
    upstream = network + "-app"
    with ExitStack() as cleanup:
        docker("network", "create", "--internal", network)
        cleanup.callback(docker, "network", "rm", network)
        docker(
            "run",
            "-d",
            "--pull=never",
            "--name",
            caddy,
            "--network",
            network,
            *caddy_container(allowlist=TEST_ALLOWLIST),
            "run",
            "--config",
            CADDY_CONFIG_IN_CONTAINER,
            "--adapter",
            "caddyfile",
        )
        cleanup.callback(docker, "rm", "-f", "-v", caddy)
        peer = docker(
            "inspect",
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            caddy,
        )
        docker(
            "run",
            "-d",
            "--pull=never",
            "--name",
            upstream,
            "--network",
            network,
            "--network-alias",
            "app",
            "--workdir",
            "/srv/smartbudget",
            "--env",
            "APP_ENV=prod",
            "--env",
            "SMARTBUDGET_HOST=localhost",
            "--env",
            f"SMARTBUDGET_CADDY_PEER={peer}",
            "--env",
            "ADMIN_TOKEN=sec012-test-token",
            "--env",
            "SECRET_KEY=sec012-test-secret",
            "--env",
            "ENV_FILE=/dev/null",
            "--env",
            "DATABASE_URL=sqlite+pysqlite:///:memory:",
            "--mount",
            f"type=bind,source={root / 'app'},target=/srv/smartbudget/app,readonly",
            "--mount",
            f"type=bind,source={probe_file},target=/srv/smartbudget/perimeter_probe.py,readonly",
            os.environ["SMARTBUDGET_TEST_APP_IMAGE"],
            *command,
        )
        cleanup.callback(docker, "rm", "-f", "-v", upstream)
        docker(
            "exec",
            caddy,
            "curl",
            "-4kfsS",
            "--retry",
            "10",
            "--retry-connrefused",
            "--retry-delay",
            "1",
            "--max-time",
            "3",
            "https://localhost/v1/health",
        )

        probe = docker(
            "exec",
            caddy,
            "curl",
            "-4kfsS",
            "--max-time",
            "3",
            "-H",
            f"X-Forwarded-For: {peer}",
            "-H",
            "X-Forwarded-Proto: http",
            "https://localhost/__test_proxy",
        )
        assert json.loads(probe) == {
            "client": "127.0.0.1",
            "peer": peer,
            "scheme": "https",
        }

        def response(
            path: str, spoofed_ip: str = "198.51.100.1", source: str = "127.0.0.1"
        ) -> tuple[int, dict]:
            data = docker(
                "exec",
                caddy,
                "curl",
                "-4ksS",
                "--interface",
                source,
                "--max-time",
                "3",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code} %{header_json}",
                "-H",
                f"X-Forwarded-For: {spoofed_ip}",
                "-H",
                "X-Forwarded-Perimeter-Policy: admin",
                "https://localhost" + path,
            )
            status, headers = data.split(" ", 1)
            return int(status), json.loads(headers)

        assert response(PERIMETER_AUTH_PATH)[0] == 404
        assert response("/v1/health", "127.0.0.1", source="127.0.0.2")[0] == 403
        direct = docker(
            "exec",
            upstream,
            "python",
            "-c",
            "import httpx, sys; print(httpx.get('http://127.0.0.1:4000' + sys.argv[1], "
            "headers={'X-Forwarded-For': sys.argv[2], 'X-Forwarded-Proto': 'https', "
            "'X-Forwarded-Perimeter-Policy': 'admin'}).status_code)",
            PERIMETER_AUTH_PATH,
            peer,
        )
        assert direct == "404"

        for i in range(20):
            status, headers = response("/v1/feedback/recent", f"198.51.100.{i + 1}")
            if i < 5:
                assert status == 403  # The original request reached require_admin.
            else:
                assert status == 429
                assert headers["retry-after"] == ["900"]
        status, headers = response("/products/1/releases")
        assert status == 429
        assert headers["retry-after"] == ["1"]  # Shared Generic Admin perimeter bucket.
        for path in ("/", "/static/css/style.css", "/v1/health"):
            assert response(path)[0] == 200
