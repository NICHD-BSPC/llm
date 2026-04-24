LLM containers
==============

In `NICHD's Bioinformatics and Scientific Programming Core <https://bioinformatics.nichd.nih.gov>`__, we wanted to use multiple LLM agent tools in a secure way on multiple systems. 

So, this repo supports:

**Agent harnesses**

- Codex CLI, using models hosted by OpenAI enterprise using ChatGPT Enterprise authentication
- Claude Code CLI, using models hosted by Amazon Bedrock using AWS SSO

**Containers**

- Podman, for running on a local Mac
- Singularity, for running on a Linux HPC system

**Tools**

- :cmd:`refresh.py` to refresh your credentials and optionally push them to a remote system
- :cmd:`launch.py` to launch a container running the LLM tool
- :cmd:`build.py` to build container images (only required if you want to build your own; you can use our hosted images)

**Also supports**

- Enterprise SSL/TLS interception
- Mounting existing conda environments and prepending them to the PATH so agents can use the tools

When everything is set up, usage looks like this:

.. code-block:: bash

   # refresh credentials if needed
   refresh.py

   # run Codex in a container
   launch.py codex

   # or Claude Code
   launch.py claude

Or, to use on a remote machine:

.. code-block:: bash

   # on local machine
   refresh.py --remote <hostname>

   # then log in to hostname, and
   launch.py codex

**Contents**

.. toctree::

   getting-started-codex
   getting-started-claude
   tools
   container-notes
