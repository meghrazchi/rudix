"""Tests for F347 safe guidance mode classification."""

from __future__ import annotations

from app.domains.chat.services.answer_mode_service import AnswerModeService


class TestAnswerModeService:
    def setup_method(self) -> None:
        self.service = AnswerModeService()

    def test_classifies_source_scope_help_as_guidance(self) -> None:
        result = self.service.classify(question="How do I choose a source scope?")
        assert result.mode == "guidance"
        assert result.topic == "source_scope"

    def test_classifies_onboarding_help_as_guidance(self) -> None:
        result = self.service.classify(question="How do I get started with Rudix?")
        assert result.mode == "guidance"
        assert result.topic == "onboarding"

    def test_classifies_citation_ui_help_as_guidance(self) -> None:
        result = self.service.classify(question="How do I inspect citations?")
        assert result.mode == "guidance"
        assert result.topic == "ui_help"

    def test_classifies_policy_question_as_grounded(self) -> None:
        result = self.service.classify(question="What is the leave policy?")
        assert result.mode == "grounded"
        assert result.topic is None

    def test_classifies_contract_question_as_grounded(self) -> None:
        result = self.service.classify(question="What does the contract liability clause say?")
        assert result.mode == "grounded"
        assert result.topic is None

    def test_classifies_connector_grounded_question_as_grounded(self) -> None:
        result = self.service.classify(question="What does the Jira ticket say about release risk?")
        assert result.mode == "grounded"
        assert result.topic is None
