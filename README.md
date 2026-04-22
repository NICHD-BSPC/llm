# LLM Tools

This repository provides tools and documentation for using LLMs securely at NIH
on the command line, including local container workflows and HPC use on systems
such as Biowulf.

Documentation is published at:

https://nichd-bspc.github.io/llm/

If you are looking for web-based chat interfaces rather than command-line tools,
see:

- [HHS Claude](https://go.hhs.gov/claudeai)
- [HHS ChatGPT](https://go.hhs.gov/chatgpt)
- [HHS Gemini](https://go.hhs.gov/gemini)

Everything here assumes familiarity with [NIH AI guidance](http://www.nihlibrary.nih.gov/resources/subject-guides/generative-ai-nih/policies-guidelines),
including restrictions around PII, pre-decisional information, and other
sensitive content.

## Quick start

Use the documentation site for:

- Getting started with Codex via ChatGPT Enterprise
- Setting up AWS STRIDES SSO for Claude Code and Bedrock
- Creating the project conda environment
- Building and running Podman or Singularity containers
- Reviewing Claude Code and launcher configuration details

## Repository contents

This repository contains:

- Utility scripts: `build.py`, `launch.py`, `refresh.py`
- Container definitions: `Dockerfile`, `env.yml`
- Documentation source: `docs/`

The Sphinx source in `docs/` is the single source of truth for documentation.
