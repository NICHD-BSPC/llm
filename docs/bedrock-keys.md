# Amazon Bedrock keys

> [!IMPORTANT] Contents
> [TOC]

Claude Code uses the AWS SDK, so `aws sso login` works. But not all tools use the AWS SDK. In such cases, you can get a short-term Bedrock token. You can use the examples at https://github.com/aws/aws-bedrock-token-generator-python, or you can use the `refresh.py` script which implements those examples.

Note that this token expires in 12 hours or when the role session credentials of the creator expire – whichever is sooner. The SSO session itself lasts ~8 hrs (see [aws-sso](aws-sso.md)), but the underlying role session credentials for the default "AWSPowerUser" role expire every hour. Tools that use the AWS SDK refresh these automatically, but the Bedrock bearer token is fixed at creation time, so in practice it has a max lifetime of ~1 hr. The `refresh.py` script prints out the expiration time.

> [!NOTE]
> Increasing the Bedrock token expiration would likely require AWS admin to change the timeout for AWSPowerUser role to longer than 1 hr.


## Prerequisites

- You have AWS SSO set up (see [aws-sso](aws-sso.md))
- You have successfully authenticated via `aws sso login`
- The `aws-bedrock-token-generator-python` package is installed. If you're using the [conda env](conda-env.md) specified here, it's already installed in that environment.

## Getting a token

`refresh.py` requests a 12-hour Bedrock token and reports the actual maximum
duration based on the current AWS SSO credential expiry.

The convention is to set this token to the `AWS_BEARER_TOKEN_BEDROCK` environment variable. To do so, run the following:

```bash
eval "$(./refresh.py --bedrock-export)"
```

The script prints `export AWS_BEARER_TOKEN_BEDROCK=....`, so the `eval` part will actually run that export in the current bash environment.

> [!NOTE] Check
> You know it’s working when the following command gives a successful JSON output in response to the prompt, "say hi":
> 
> ```bash
> curl -sS -X POST \
> "https://bedrock-runtime.us-east-1.amazonaws.com/model/us.anthropic.claude-3-5-haiku-20241022-v1:0/converse" \
> -H "Content-Type: application/json" \
> -H "Authorization: Bearer $AWS_BEARER_TOKEN_BEDROCK" \
> -d '{"messages":[{"role":"user","content":[{"text":"Say hi"}]}]}' | jq .
> ```

*Back to [README.md](../README.md)*
