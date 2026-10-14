"""Finder for therapists, psychologists and psychiatrists who publish how to reach them.

Pipeline: Google (SERP) finds profiles -> rules (+ Gemini for the ambiguous) keep real clinicians ->
Instagram bio / the clinician's own website give the channel they publish -> a person reviews and
approves before anything is exported. Only public, self-published information is used; LinkedIn
pages are never fetched.
"""
