# ChatGPT Enterprise Sign On

The current HHS ChatGPT Enterprise instance allows anyone to log in with NIH credentials through the website. We can use this to authenticate Codex from the command line.

## Prerequisites

- [Install Codex](https://developers.openai.com/codex/cli) on the local machine.

## Sign on with Codex

- From the terminal, run `codex`.
- Upon first starting, select the first login option. This will open a browser for single sign-on using your NIH credentials.
- Codex will wait in the background while you log in.
- Upon logging in, the running Codex instance will automatically detect the login.

The file `~/.codex/auth.json` will be created with your credentials. **Treat this file like a password** since it allows Codex to authenticate as you. The [`refresh.py`](refresh.py) script can be used to do this in the future as well as push the credentials to a remote like Biowulf.

> [!note] Check
> You are complete with this step when you type `test` into Codex and the model sends a response.

*Back to [README.md](../README.md)*
