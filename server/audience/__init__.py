"""The audience of MMTF's OWN accounts: who comments on our posts, and who needs a human reply.

Everything here is restricted by design:
  * only accounts listed in MMTF_OWN_ACCOUNTS are ever collected, and each post's owner is checked;
  * comments are triaged by transparent rules (no third-party LLM sees them);
  * the output is a reply queue for people, never a marketing list: public replies, no cold DMs.
"""
