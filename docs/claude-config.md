# Claude Code config

Things change quickly; the authoritative source is always the [Claude Code settings documentation](https://code.claude.com/docs/en/settings).

## Files

- `~/.claude/settings.json` has general settings. This is the one you will likely be editing.
- `~/.claude.json` has general state (metrics, which directories you have approved, etc). It can be helpful to mount into a container so that the instance running in the container remembers which directories you've approved.
- `~/.claude` (the entire directory) stores session history, skills, and other persistent state. It can be helpful to mount into a container to have access to all of that, however, this means the container will have access to prior chat logs as well.

Project-level configs can be also set, see [Claude Code settings documentation](https://code.claude.com/docs/en/settings).

For notes on configs in containers, see [container-notes](container-notes.md#persistent-mounts-and-configs).

> [!NOTE]
> Config is in JSON format. Examples below will be written as complete JSON (all config wrapped in `{` and `}`). JSON does not formally support comments. Ensure there is no trailing comma on the last entry. 
> 
> As an example, if your file looks like this:
> 
> ```json
> {
>   "option1": "1"
> }
> ```
> 
> and an example here shows:
> 
> ```json
> {
>   "env": {
>     "AWS_PROFILE": "my-profile"
>   }
> }
> ```
> 
> then you would edit yours to:
> 
> ```json
> {
>   "option1": "1",
>   "env": {
>     "AWS_PROFILE": "my-profile"
>   }
> }
> ```
> 
> (note the comma after `"1"`).

## AWS SSO

### Environment variables

Using Amazon Bedrock, Claude Code running inside or outside a container will always need `AWS_PROFILE`, `AWS_REGION` and `CLAUDE_CODE_USE_BEDROCK` to be set. It uses the AWS env vars to look up the credentials in `~/.aws`. That means this directory must be available when running in a container, which is why `launch.py` mounts this directory automatically when running a container.


```bash
CLAUDE_CODE_NO_FLICKER=1
CLAUDE_CODE_USE_BEDROCK=1
AWS_PROFILE=your-profilename
AWS_REGION=us-east-1
```



### Refreshing credentials

When running natively on a local machine (see [container-notes terminology](container-notes.md#terminology), Claude Code can automatically refresh credentials if you have this:

```json
{
  "awsAuthRefresh": "aws sso login --profile AWSPowerUserAccess-000001"
}
```

However, when in a container, it will try to refresh credentials with this command but it won't be able to see the response from logging in, and instead you'll need to run `refresh.py`. This may need a restart of Claude Code and the container, so you will want to take advantage of [resuming conversations in a container](running-containers.md#resuming).

## Custom status line

Copy the [`tools/claude-status.sh`](../tools/claude-status.sh) file to your `~/.claude` directory, and add this to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/claude-status.sh"
  }
}
```

The prompt will look like this, with P=prompt percentage, I=input tokens, O=output tokens, R=cache read tokens, W=cache write tokens. Price is estimated internally by Claude Code; this just shows it.

```text
[Opus 4.6] /Users/dalerr/proj/llm/docs | P:8% | I:3 | O:20 | R:0 | W:15821 | $0.10 | 2m 40s
/home/devuser/.claude/projects/-demo/5b189fb5-1b22-4c78-a8dc-5ddd0b5b254c.jsonl
```
