# Local and remote

> [!important] Contents
> [TOC]

Here, we use the term **local** to refer to running directly on a laptop or desktop, and **remote** to refer to a host that may be living in a data center, like Biowulf.

The distinction is important because the available login methods *need to run on a computer with a web browser that can redirect to localhost* which is typically only the case on a local machine.

## Login concepts

The current login methods available are single sign-on. This involves logging in through a web browser. The login process requires the browser to be able to redirect to a particular port on localhost. In practice, this means you have to perform the login process on a local machine, and then copy the credentials to a remote machine afterwards.

That is:

- `codex login` --> opens browser to https://auth.openai.com/log-in --> log in --> website redirects to localhost, where Codex is listening --> Codex saves to `~/.codex/auth.json`

- `aws sso login` --> opens browser to https://nih.awsapps.com/start --> log in --> website redirects to localhost, where `aws` is listening --> `aws` saves to `~/.aws/sso`

So if you were to run `codex login` on Biowulf, it would print a URL to visit. If you pasted it into a local browser and logged in, the website would redirect to your local machine...but Codex would still be listening on Biowulf, and the redirect would never make it there.

*Back to [README.md](../README.md)*
