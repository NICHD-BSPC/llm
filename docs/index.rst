LLM containers
==============

In `NICHD's Bioinformatics and Scientific Programming Core <https://bioinformatics.nichd.nih.gov>`__, we wanted to use multiple LLM agent tools in a secure way on multiple systems. 


**Agent harnesses:**

- Codex CLI, using models hosted by OpenAI enterprise using ChatGPT Enterprise authentication
- Claude Code CLI, using models hosted by Amazon Bedrock using AWS SSO

**Containers:**

- Podman, for running on a local Mac
- Singularity, for running on a Linux HPC system

**Tools**

- :cmd:`refresh.py` to refresh your credentials and optionally push them to a remote system
- :cmd:`launch.py` to launch a container running the LLM tool
- :cmd:`build.py` to build container images (only required if you want to build your own; you can use our hosted images)

**Also supports:**

- Enterprise SSL/TLS interception
- Mounting existing conda environments and prepending them to the PATH so agents can use the tools

When everything is set up, usage looks like this:

.. code-block:: bash

   # refresh credentials
   refresh.py --remote <remote hostname>

   # run Codex in a container
   launch.py codex

   # or Claude Code
   launch.py claude

Or a slightly more advanced command: give Codex access to a conda environment, support custom SSL/TLS certs for running over VPN, and resume a previous session:

.. code-block:: bash

   launch.py --certs certs.pem --conda-env ./env codex --resume 019da126-823a-7993-9fb6-0410bf9ceb54


**Contents**

.. toctree::

   getting-started-codex
   getting-started-claude
   tools
   container-notes

