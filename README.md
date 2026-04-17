# LLM tools

This repo provides a set of documentation and tools for using LLMs in a secure
manner at NIH on the command line -- including on Biowulf.

It is a collection of markdown documentation and utility scripts.

This repo is for *command-line interfaces*. If you're looking for web-based chat interfaces, see

- [HHS Claude](https://go.hhs.gov/claudeai)
- [HHS ChatGPT](https://go.hhs.gov/chatgpt)
- [HHS Gemini](https://go.hhs.gov/gemini)

> [!WARNING]
> ***Everything here assumes you are familiar with [NIH AI guidance](http://www.nihlibrary.nih.gov/resources/subject-guides/generative-ai-nih/policies-guidelines).*** This includes, but is not limited to:
> - No PII
> - No pre-decisional information
> - Do not use as a proxy for software development
> - Do not use to help develop or review prepublication information that could be misused or cause the NIH, or any research subjects, any real or perceived harm.

## Getting started

[Codex](https://developers.openai.com/codex/cli) and [Claude Code](https://code.claude.com/docs/en/overview) are currently supported here. They can both be run natively, or with additional security in a podman container (usually on a local machine) or in a Singularity container (usually on HPC, like Biowulf). Authentication and configuration needs to be handled differently for each of them. This repo provides the tools for easily working with the login, especially in containers.

- **If you plan to use Codex**, start with [Setting up ChatGPT Enterprise sign-on](docs/chatgpt-enterprise.md).

- **If you plan to use Claude Code**, start with [Setting up AWS STRIDES single sign-on (SSO)](docs/aws-sso.md). This allows you to use models hosted on Amazon Bedrock, including those from Anthropic. In contrast to Codex, there's no enterprise login we can use for Anthropic models, it's a little more complex to set up.

- **If you plan to use containers**, see:
  1. [Notes on containers](docs/container-notes.md) for introduction and context
  1. [Building containers](docs/building-containers.md) for building podman/docker/singularity containers. If you are primarily interested in doing this on Biowulf, only one person in your group needs to do this and push the image to a shared location.
  1. [Creating a conda environment](docs/conda-env.md) on your local machine to set up for using the container runners. This lets you use the [`refresh.py'](refresh.py) script for logging in as well as pushing credentials to a remote like Biowulf.
  1. [Running agents in containers](docs/running-containers.md) to use them in practice. Once everything is set up, this will be the main section of interest.
  1. [Tools](docs/tools.md) in this repo

- **Configuration:**
 - [Claude Code config](docs/claude-config.md)
 - [Codex config](docs/codex-config.md)


- **Other info:**
  - Comparisons
  - [Local vs remote](docs/local-remote.md), a note on nomenclature used here
  - [Bedrock API keys](docs/bedrock-keys.md) for when you can't use AWS SSO
