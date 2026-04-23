.. _start-codex::

Getting started: Codex
======================

At NIH, due to the currently configured login processes, it is more
straightforward to get up and running with Codex. So this section will walk you
through setting up Codex locally on your Mac laptop, then running it locally in
a Podman container, then running it on a remote system in a Singularity
container.

Step 1: Codex locally (native)
------------------------------

The minimal first step is to confirm that the Codex CLI works locally.

1. Install `Codex CLI <https://developers.openai.com/codex/cli>`__ on your local machine.
2. Navigate to a directory you are comfortable letting Codex see. This will likely NOT be your home directory.
3. Run :cmd:`codex` from the terminal.
4. On first start, select the first login option. This opens a browser
   single sign-on. Codex waits in the background while you log in.
5. After successful login, the running Codex instance detects the login
   automatically.
6. Type in a prompt (even just the word "testing") and things are working if
   model responds.
7. Ctrl-C twice, or :cmd:`/exit` to quit.

.. details:: What did this do?

   Upon logging in with Codex, the file :file:`~/.codex/auth.json` was created with
   your credentials. We will be transporting this file into containers and to
   the remote host to authenticate in Codex instances running there. Treat this
   file like a password because it allows Codex to authenticate as you.

Step 2: Codex locally (podman container)
----------------------------------------

Running Codex as above still can allow read access to your entire computer.
While updates to Codex are improving the sandboxing capabilities, running in
a container helps isolate further by only mounting what is needed into the container.

After confirming you have a local native instance of Codex working as described
above, do the following:

1. Install `Podman Desktop <https://podman-desktop.io/>`__ and ensure it is running.
2. Download the :file:`launch.py` script from this repo; it is most convenient to put it on your PATH.
3. Navigate to a directory your are comfortable letting Codex see
4. Run the following; it may take a few seconds the first time:

   .. code-block:: bash

      launch.py codex --image-name ghcr.io/nichd-bspc/llm

5. Similar to above, submit a prompt to confirm that the model replies.
6. Ctrl-C twice, or :cmd:`/exit` to quit.

.. details:: What did this do?

   - :cmd:`launch.py` detected you're running on a Mac and that Podman is the
     appropriate container runtime.
   - Podman downloaded the image we created and hosted (which has Codex and Claude
     Code installed)
   - Podman started up the image to create a container
   - Mounted the current working directory into the container (done automatically
     by the launch script)
   - Mounted your :file:`~/.codex/auth.json` into the container so that the isolated
     Codex instance in the container could log in (also done by the launch script)
   - Started Codex in the running container, waiting for your input. Codex was
     started with the ``--sandbox danger-full-access`` argument, effectively
     disabling Codex's sandbox because we are using th container for isolation.
   - Exiting Codex automatically exited the container.

.. note::

   If you are on VPN, or otherwise on a network that is intercepting your
   SSL/TLS traffic, you may get connection errors. This happens because the
   container cannot see the enterprise certificates installed on your machine
   (remember, one goal of the container is to isolate it, and this is a symptom
   of that isolation). So we have to pass them in to the container.. Download
   your enterprise certificates and save them somewhere convenient. For NIH
   specifically (only available on the NIH network), you can download them like
   this, saving to a file :file:`~/.certs.pem`:

   .. code-block:: bash

      curl -fSsL -o ~/.certs.pem http://nihdpkicrl.nih.gov/certdata/DPKI-2023-Intermediate-rekey-FullChainBase64.crt

   Then you need to modify the command like this:

   .. code-block:: bash

      launch.py codex --image-name ghcr.io/nichd-bspc/llm --certs ~/.certs.pem codex

   For convenience, you can use the environment variable
   ``LLM_DEVCONTAINER_CERTS`` to control the ``--certs`` default.


Step 3: Remote Codex (Singularity)
----------------------------------

Next, we'll run Codex on a remote system (like NIH's Biowulf HPC).

1. Download the :file:`refresh.py` script from this repo locally; it is most
   convenient to put it on your PATH.
2. Run it like this; in this example we're using NIH's Biowulf as the hostname
   and connecting as our current username; modify as appropriate for your
   situation:

   .. code-block:: bash

      refresh.py --kind codex --remote biowulf.nih.gov

3. Log in to the remote system. If using NIH's Biowulf, get an interactive node
   and load the Singularity module:

   .. code-block:: bash

      ssh biowulf.nih.gov      # log in
      sinteractive             # allocate interactive node
      module load singularity  # make Singularity available

4. Download the :file:`launch.py` script from this repo to the remote. If you want
   a one-liner, this will put it in your home directory (:file:`~/launch.py`) but
   you may want to put it somewhere on your PATH for convenience.

   .. code-block:: bash

      curl -fSsL -o ~/launch.py https://github.com/nichd-bspc/llm/launch.py

5. Run the following

   .. code-block:: bash

      launch.py codex

.. details:: What did this do?

   - The refresh script checked to see if you were logged in to Codex on the
     local machine. If not, it ran :cmd:`codex login` to refresh the
     :file:`~/.codex/auth.json` file
   - Then it used rsync to transport the local copy of :file:`~/.codex/auth.json` to the remote system
   - We need the launcher script on the other system, hence needing to download it there
   - :cmd:`launch.py codex` identified that we were on a Linux machine so that we
     should use Singularity, downloaded the Singularity image, disabled
     Singularity's default behavior of mounting your *entire* home directory,
     mounted :file:`~/.codex` into the container (which includes the ``auth.json``
     credentials), and started Codex.

Step 4: Codex configuration
---------------------------

TODO
