"""Demo provider toggle: local Ollama <-> Azure OpenAI.

No network: azure_available() is monkeypatched. Verifies the toggle only
engages azure when configured (so the demo button never lands on a dead
provider), that _call_llm records per-call latency + provider telemetry, and
that the local path still routes through Ollama.
"""

from __future__ import annotations

from systems import conversation


def _reset(monkeypatch, azure=False):
    monkeypatch.setattr(conversation, "_provider", "local")
    monkeypatch.setattr(conversation, "azure_available", lambda: azure)


def test_toggle_stays_local_when_azure_unconfigured(monkeypatch):
    _reset(monkeypatch, azure=False)
    assert conversation.toggle_provider() == "local"  # cannot engage a dead provider
    assert conversation.current_provider() == "local"


def test_toggle_engages_azure_when_configured(monkeypatch):
    _reset(monkeypatch, azure=True)
    assert conversation.toggle_provider() == "azure"
    assert conversation.current_provider() == "azure"
    assert conversation.toggle_provider() == "local"  # flips back


def test_call_llm_records_latency_and_provider(monkeypatch):
    _reset(monkeypatch, azure=False)

    class _FakeClient:
        def chat(self, **kwargs):
            return {"message": {"content": '{"reply": "hi"}'}}

    monkeypatch.setattr(conversation, "_get_client", lambda: _FakeClient())
    out = conversation._call_llm(system="s", user="u")
    assert out == '{"reply": "hi"}'
    assert conversation._last_provider == "local"
    assert conversation.last_call_seconds() >= 0.0  # telemetry recorded


def test_call_llm_falls_back_to_local_when_provider_azure_but_unconfigured(monkeypatch):
    # Provider says azure but creds are absent -> dispatcher must use local.
    monkeypatch.setattr(conversation, "_provider", "azure")
    monkeypatch.setattr(conversation, "azure_available", lambda: False)
    captured = {}

    class _FakeClient:
        def chat(self, **kwargs):
            captured["used"] = True
            return {"message": {"content": "{}"}}

    monkeypatch.setattr(conversation, "_get_client", lambda: _FakeClient())
    conversation._call_llm(system="s", user="u")
    assert captured.get("used") is True  # routed to local Ollama, not azure
    assert conversation._last_provider == "local"


def test_azure_call_uses_json_mode_and_deployment(monkeypatch):
    # Drive _call_azure directly with a fake client to confirm request shape.
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini-demo")
    captured = {}

    class _Msg:
        content = '{"reply": "from cloud"}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _FakeAzure:
        chat = _Chat()

    monkeypatch.setattr(conversation, "_get_azure_client", lambda: _FakeAzure())
    out = conversation._call_azure("sys", "usr", json_format=True, num_predict=200,
                                   temperature=0.8, history=None)
    assert out == '{"reply": "from cloud"}'
    assert captured["model"] == "gpt-4o-mini-demo"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["messages"][0]["role"] == "system"
