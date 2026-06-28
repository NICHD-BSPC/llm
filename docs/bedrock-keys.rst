Amazon Bedrock keys
===================

Claude Code and Pi use the AWS SDK, so the setup documented elsewhere in these
docs uses :cmd:`aws sso login`. However, not all tools use the AWS SDK. In
those cases, you can get a short-term Bedrock token. You can use the examples
at https://github.com/aws/aws-bedrock-token-generator-python, or use
:cmd:`refresh.py`, which implements those examples.


:nih:`NIH-specific` In practice, this token expires **every hour**. Technically,
it expires in 12 hours or when the role session credentials of the creator
expire, whichever happens sooner. The SSO session itself lasts roughly eight
hours; see :doc:`aws-sso`. But the underlying role session credentials for the
default ``AWSPowerUser`` role expire every hour, and this is what sets the
practical token expiration time.

Tools using the AWS SDK refresh those automatically, but the Bedrock bearer
token is fixed at creation time, so in practice it often has a maximum lifetime
of about one hour. :cmd:`refresh.py` prints the expiration context.

.. note::

   Increasing the Bedrock token expiration would likely require AWS admins to
   increase the timeout for the ``AWSPowerUser`` role beyond one hour.

Prerequisites
-------------

- AWS SSO is set up; see :doc:`aws-sso`.
- You have successfully authenticated with :cmd:`aws sso login`.
- :cmd:`aws-bedrock-token-generator-python` is installed. If you use the
  conda environment from :file:`env.yml` in the repository root, it is
  already included there.

Getting a token
---------------

:ref:`refresh` requests a 12-hour Bedrock token and reports the actual maximum
duration based on the current AWS SSO credential expiry.

The usual convention is to place this token in the
``AWS_BEARER_TOKEN_BEDROCK`` environment variable:

.. code-block:: bash

   eval "$(./refresh.py --bedrock-export)"

The script prints an ``export AWS_BEARER_TOKEN_BEDROCK=...`` command, and
``eval`` runs that export in the current shell.

In order to use this on a remote machine, you would need to capture the token
and manually export it into the relevant environment, likely by copy-pasting.

.. tip::

   You know it is working when the following command returns successful JSON in
   response to the prompt ``Say hi``:

   .. code-block:: bash

      curl -sS -X POST \
      "https://bedrock-runtime.us-east-1.amazonaws.com/model/us.anthropic.claude-haiku-4-5-20251001-v1:0/converse" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $AWS_BEARER_TOKEN_BEDROCK" \
      -d '{"messages":[{"role":"user","content":[{"text":"Say hi"}]}]}' | jq .
