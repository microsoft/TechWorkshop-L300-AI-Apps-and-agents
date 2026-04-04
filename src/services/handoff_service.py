"""
Handoff service using optimized domain-based routing pattern.

This replaces the legacy handoff logic with the Agent-based pattern
from handoff_agent.py, providing:
- Intent classification with structured outputs
- Lazy classification for efficiency
- Domain-based agent routing
- Context transfer on handoff
"""

import logging
import os
import random
import json
from typing import Any, Dict, Optional, Tuple

from openai import AzureOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class IntentClassification(BaseModel):
    """Structured output for intent classification."""
    model_config = {"extra": "forbid", "additionalProperties": False}
    domain: str = Field(
        description="Target domain: cora, interior_designer, inventory_agent, customer_loyalty, or cart_manager"
    )
    is_domain_change: bool = Field(
        description="Whether this represents a change from the current domain"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0"
    )
    reasoning: str = Field(
        description="Brief explanation of the classification decision"
    )


# Domain definitions mapping to existing agents
AGENT_DOMAINS = {
    "cora": {
        "name": "Cora Shopping Assistant",
        "description": "General shopping assistance, product browsing"
    },
    "interior_designer": {
        "name": "Interior Design Specialist",
        "description": "Room design, color schemes, furniture recommendations, image creation"
    },
    "inventory_agent": {
        "name": "Inventory Specialist",
        "description": "Product availability, stock levels, inventory checks"
    },
    "customer_loyalty": {
        "name": "Customer Loyalty Specialist",
        "description": "Discounts, promotions, loyalty programs, customer benefits"
    },
    "cart_manager": {
        "name": "Cart Manager Specialist",
        "description": "Shopping cart operations, adding/removing items, cart viewing, checkout assistance"
    }
}


class HandoffService:
    """
    Handoff service using intent classification for domain routing.
    
    This class replaces the legacy call_handoff/select_agent pattern with
    a more robust intent classification approach.
    """
    
    def __init__(
        self,
        azure_openai_client: AzureOpenAI,
        deployment_name: str,
        default_domain: str = "cora",
        lazy_classification: bool = True
    ):
        """
        Initialize handoff service.
        
        Args:
            azure_openai_client: Azure OpenAI client for intent classification
            deployment_name: Model deployment name for classification
            default_domain: Default domain when no current domain exists
            lazy_classification: Enable lazy classification (check response for handoff markers)
        """
        self.client = azure_openai_client
        self.deployment = deployment_name
        self.default_domain = default_domain
        self.lazy_classification = lazy_classification
        
        # Session state: domain per session
        self._session_domains: Dict[str, str] = {}
        
        logger.info(
            f"[HANDOFF_SERVICE] Initialized with default_domain={default_domain}, "
            f"lazy_classification={lazy_classification}"
        )
    
    def classify_intent(
        self,
        user_message: str,
        session_id: str,
        chat_history: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Classify user intent and determine target domain.
        
        Args:
            user_message: User's message to classify
            session_id: Session identifier for tracking current domain
            chat_history: Optional chat history for context
            
        Returns:
            Dictionary with keys: domain, is_domain_change, confidence, reasoning, agent_id, agent_name
        """
        print("Beginning intent classification...")
        current_domain = self._session_domains.get(session_id, None)
        
        # If no current domain, route to default
        if not current_domain:
            logger.info(f"[HANDOFF_SERVICE] First message for session {session_id}, routing to {self.default_domain}")
            self._session_domains[session_id] = self.default_domain
            
            return {
                "domain": self.default_domain,
                "is_domain_change": True,
                "confidence": 1.0,
                "reasoning": f"First message, routing to {self.default_domain}",
                "agent_id": self.default_domain,
                "agent_name": AGENT_DOMAINS[self.default_domain]["name"]
            }
        
        # Build classification prompt
        prompt = f"""
            Current domain: {current_domain}
            User message: {user_message}
        """
        
        try:
            print("Sending classification request to LLM...")
            conversation = self.client.conversations.create(
                items = [
                    {
                        "type": "message",
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            print(f"Created conversation for classification: {conversation.id}")

            response = self.client.responses.create(
                conversation=conversation.id,
                extra_body={"agent_reference": {"name": "handoff-service", "type": "agent_reference"}},
                input=""
            )

            print("Received classification response.")
            
            # Extract structured result
            intent = json.loads(response.output_text)
            
            result = {
                "domain": intent["domain"],
                "is_domain_change": intent["is_domain_change"],
                "confidence": intent["confidence"],
                "reasoning": intent["reasoning"],
                "agent_id": intent["domain"],
                "agent_name": AGENT_DOMAINS.get(intent["domain"], {}).get("name", "Unknown Agent")
            }
            print("Updating session domain if changed...")
            
            # Update session domain if changed
            if intent["is_domain_change"]:
                self._session_domains[session_id] = intent["domain"]
                logger.info(f"[HANDOFF_SERVICE] Domain change for session {session_id}: {current_domain} -> {intent['domain']}")
            
            logger.info(f"[HANDOFF_SERVICE] Intent classification: {result}")
            return result
            
        except Exception as exc:
            logger.error(f"[HANDOFF_SERVICE] Intent classification failed: {exc}", exc_info=True)
            
            # Fallback: stay with current domain or use random
            fallback_domain = current_domain or self.default_domain
            
            logger.warning(f"[HANDOFF_SERVICE] Falling back to domain: {fallback_domain}")
            
            return {
                "domain": fallback_domain,
                "is_domain_change": False,
                "confidence": 0.3,
                "reasoning": f"Classification error, using {fallback_domain}",
                "agent_id": fallback_domain,
                "agent_name": AGENT_DOMAINS.get(fallback_domain, {}).get("name", "Unknown Agent")
            }
    
    def get_current_domain(self, session_id: str) -> Optional[str]:
        """Get current domain for a session."""
        return self._session_domains.get(session_id)
    
    def set_domain(self, session_id: str, domain: str) -> None:
        """Manually set domain for a session."""
        if domain not in AGENT_DOMAINS:
            logger.warning(f"[HANDOFF_SERVICE] Unknown domain: {domain}, using default: {self.default_domain}")
            domain = self.default_domain
        
        self._session_domains[session_id] = domain
        logger.info(f"[HANDOFF_SERVICE] Set domain for session {session_id}: {domain}")
    
    def reset_session(self, session_id: str) -> None:
        """Reset session domain."""
        if session_id in self._session_domains:
            del self._session_domains[session_id]
            logger.info(f"[HANDOFF_SERVICE] Reset session {session_id}")
