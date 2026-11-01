# 4. Gateway-neutral channels

**Decision.** The USSD, SMS and voice logic knows nothing about a provider. Thin adapters translate
each gateway's webhook format. The default wire format is the common `CON`/`END` USSD convention.

**Why.** Africa's Talking's published country list does not include Burundi, so we cannot assume
it. Reaching subscribers means an agreement with an in-country aggregator or operator, and short
codes need approval from the regulator, ARCT. The provider is still an open question.

**Consequence.** Swapping aggregators is a small change. Burundi operator access remains a
partnership task, not an engineering one.
