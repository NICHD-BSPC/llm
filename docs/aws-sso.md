# Setting up AWS STRIDES Single Sign-On

> [!important] Contents
> [TOC]

**Why?** AWS SSO is required for using Amazon Bedrock models, e.g., for Claude Code. If
you're only using Codex, you don't need this.

Setting up AWS SSO allows *any* tool using the AWS SDK to authenticate as well,
so it does afford substantial flexibility.

It is possible to use Azure or Google Cloud Platform instead of AWS, but this is not documented here yet.

## Prerequisites

- You have an AWS STRIDES account already set up
- You have the list of names of the people to include in a security group who will be able to log in to AWS

## 1. Account provisioning (one time per group)

First, you need to get the relevant accounts added to the AWS Identity Center, which enables SSO. This is a manual setup on CIT’s part since NIH’s integration with EntraID is not yet complete.

This is initial setup -- it only needs to be done once per group.

- Submit a [Cloud Operations Support Request](https://myitsm.nih.gov/nih_sd?id=nih_sd_sc_item&sys_id=db4dc8a91b41dc1001e9ea82f54bcb2c) on ServiceNow. Include:
  - AWS account name and number
  - List of people (names, usernames, emails)
  - Existing security group name to use (that already contains the users) or the name of a new security group for CIT to create with these users
  - The role to assign users in the security group. See here (requires AWS Console access) for policy details on each role. We are currently using "NIH-AWS-PowerUser" role, one of the standard roles set up in an AWS STRIDES account.
- After answering any other questions CIT has, then:
  - CIT will either send each user an email directly or cause one to be sent through AWS (the latter appeared to have issues, so this may need more manual intervention on CIT’s part). The email will contain your username, a temp password, and a URL
  - Visit the URL, log in, change the password, set up MFA

> [!note] Check
> You are complete with this phase when you can successfully log in to https://nih.awsapps.com/start

## 2. AWS CLI v2 setup (one time per user)

AWS CLI v2 is used to authenticate with AWS. It is used by Claude Code to automatically refresh credentials whenever possible, and is also useful for working with API keys (see [Bedrock API keys](bedrock-keys.md))

- Install the [AWS Command Line Interface (AWS CLI) Version 2](https://aws.amazon.com/cli/) and ensure it is on your `$PATH`.
  - **If you plan to use the container tools in this repo**, you should create the conda environment as documented at [Conda env](conda-env.md).
  - **If you already have it installed**, make sure you are using version 2. See the [v1 to v2 migration docs](https://docs.aws.amazon.com/cli/latest/userguide/cliv2-migration.html) if you need to upgrade. Or you can use the conda env, since it is isolated from any existing installation.

> [!note] Check
> You are complete with this phase when you open a new terminal (activating the conda env if needed) and running `aws` gives the following, which shows that the tool is installed and responding:
>
> ```text
> aws: [ERROR]: the following arguments are required: command
> ```

## 3. Set up AWS SSO (one time per user)

Run `aws configure sso` and respond as follows.

The items you need to type/paste are indicated here with `**`, otherwise hit Enter to accept defaults. **The account number 00001 is used as a placeholder**, you will need to fill in your own account number in all these commands.

Note that as part of this process, a browser window will pop up where you need to authenticate.

```text
** SSO session name (Recommended): aws-claude
** SSO start URL [None]: https://nih.awsapps.com/start
** SSO region [None]: us-east-1
   SSO registration scopes [sso:account:access]:
   Attempting to open your default browser.
   If the browser does not open, open the following URL:

   https://oidc.us-east-1.amazonaws.com/authorize?response_type=c.......

   The only AWS account available to you is: 00001
   Using the account ID 00001
   The only role available to you is: AWSPowerUserAccess
   Using the role name "AWSPowerUserAccess"
** Default client Region [None]: us-east-1
   CLI default output format (json if not specified) [None]:
   Profile name [AWSPowerUserAccess-00001]:
   To use this profile, specify the profile name using --profile, as shown:

   aws sts get-caller-identity --profile AWSPowerUserAccess-00001
```

You can see what it did by inspecting `~/.aws/config`.

Then run the command it suggests, again using your actual account number rather than 00001:

```bash
aws sts get-caller-identity --profile AWSPowerUserAccess-00001
```

We want to use this profile by default, so ensure you’re exporting these env vars (e.g., in your `~/.bashrc`), again with your actual account number:

```bash
export AWS_PROFILE="AWSPowerUserAccess-00001"
export AWS_REGION=us-east-1
```

Source your `.bashrc` or open a new terminal to get that env var. Run the same command but without specifying the profile. It should show the same as before but is now using your newly-configured default:

```bash
aws sts get-caller-identity
```

Here is how to inspect your credentials, for example checking the expiration when the token will need to be refreshed (Claude Code will refresh this automatically):

```bash
aws configure export-credentials
```

If you ever need to manually refresh credentials, run:

```bash
aws sso login
```

This will open a browser to log in. It may automatically say, "Your credentials have been shared successfully and can be used until your session expires. You can now close this tab."

> [!note] Check
> You are complete with this phase when you run `aws sso login` in the terminal and you get the "credentials have been shared successfully" message in a browser.

## 4. Routine usage

Once AWS SSO is set up with the above steps, it doesn't need to be touched again.

The SSO session typically lasts 8 hrs before you need to log in again. Within that window, the AWS SDK automatically refreshes the shorter-lived role credentials as needed, so you don't have to do anything.

Running

```bash
aws sso login
```

will open a browser to log in.

Importantly, *this only works on a local machine*. `aws sso login` is listening on a particular port on the machine it is called from. Upon logging in, the browser sends a response to that port on localhost. So both `aws sso login` and the browser you're logging in with need to be on the same computer

To use these credentials on another host, you can manually transfer them or use the [`refresh.py`](../refresh.py) script.

Claude Code can be configured to automatically run this any time the authentication times out, so you don't need to manually run `aws sso login` in that context.
