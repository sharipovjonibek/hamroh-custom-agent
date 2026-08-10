"""Checks for configurable deployed identity and clean public surfaces."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_NAME = "Rus" + "tam"
FORBIDDEN = (
    UPSTREAM_NAME.casefold(),
    ("rus" + "tamz.com"),
    ("hamroh " + "harness"),
    ("lu" + "na"),
    ("nodi" + "ra"),
    ("mir" + "zo"),
    ("dil" + "ya"),
    ("clau" + "dir"),
    ("bot" + "_xona"),
    ("self" + "-reflection"),
    ("reminder" + "-format"),
    ("render" + "-style"),
    ("house " + "style"),
    ("<this is a " + "reminder>"),
    ("self/" + "learn" + "ings.md"),
)


def test_deployed_prompt_uses_configurable_name_and_identifies_jonibek() -> None:
    effective_prompt = "\n".join(
        [
            (ROOT / "framework/prompts/system.md").read_text(encoding="utf-8"),
            (ROOT / "prompts/project.md").read_text(encoding="utf-8"),
        ]
    ).casefold()

    assert "agent_name" in effective_prompt
    assert ("shah" + "noza") not in effective_prompt
    assert "jonibek sharipov" in effective_prompt
    assert "developed" in effective_prompt
    assert "customized" in effective_prompt
    for forbidden in FORBIDDEN:
        assert forbidden not in effective_prompt


def test_model_loaded_skills_have_no_inherited_customizations() -> None:
    for skills_root in (ROOT / "skills", ROOT / "framework/skills"):
        for path in sorted(skills_root.rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").casefold()
            for forbidden in FORBIDDEN:
                assert forbidden not in text, f"{forbidden!r} remains in {path}"


def test_operational_links_use_jonibeks_fork() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").casefold()
    gitmodules = (ROOT / ".gitmodules").read_text(encoding="utf-8").casefold()

    assert UPSTREAM_NAME.casefold() not in readme
    assert UPSTREAM_NAME.casefold() not in gitmodules
    assert "github.com/sharipovjonibek/hamroh" in readme
    assert "github.com/sharipovjonibek/hamroh" in gitmodules


def test_agent_name_has_one_environment_source_of_truth() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    config = (ROOT / "framework/hamroh/config.py").read_text(encoding="utf-8")
    startup = (ROOT / "framework/hamroh/startup.py").read_text(encoding="utf-8")
    commands = (
        ROOT / "framework/hamroh/telegram_io/commands.py"
    ).read_text(encoding="utf-8")

    assert "AGENT_NAME=YourAgentName" in env_example
    assert 'agent_name_from_env()' in config
    assert "agent_name=config.agent_name" in startup
    assert "self.config.agent_name" in commands
