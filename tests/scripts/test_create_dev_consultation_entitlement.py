from scripts.create_dev_consultation_entitlement import (
    build_parser,
    print_booking_access,
)

BOOKING_TOKEN = "12345678-1234-1234-1234-123456789abc"


def test_default_output_masks_booking_capability(capsys):
    print_booking_access(BOOKING_TOKEN, show_full_capability=False)

    output = capsys.readouterr().out
    assert BOOKING_TOKEN not in output
    assert "/consultation/book/" not in output
    assert "12345678..." in output
    assert "--show-full-capability" in output


def test_explicit_opt_in_outputs_full_booking_capability(capsys):
    print_booking_access(BOOKING_TOKEN, show_full_capability=True)

    output = capsys.readouterr().out
    assert BOOKING_TOKEN in output
    assert f"/consultation/book/{BOOKING_TOKEN}" in output
    assert "Sensitive booking capability" in output


def test_cli_help_marks_full_capability_as_sensitive():
    help_text = build_parser().format_help()

    assert "--show-full-capability" in help_text
    assert "sensitive" in help_text
