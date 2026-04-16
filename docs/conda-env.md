# Conda env

> [!IMPORTANT] Contents
> [TOC]

Some tools in this repository have dependencies. The conda environment specification in this repo will provide those dependencies.

Specifically, you'll need additional tools for the `inspect-conversation.py` script and using the `refresh.py` script for refreshing AWS credentials.

## Prerequisites

- Conda is installed. See [instructions](https://conda-forge.org/download/); the Miniforge installation is best.


## Create the environment

This command will create a new environment named `llm`:

```bash
conda env create -n llm --file env.yml
```


## Use the environment

Any time you want to use these tools, you will need to activate the conda environment:

```bash
conda activate llm
```

Or you can put the `bin` dir of the environment on your `PATH`. To identify that directory, use:

```bash
conda run -n llm echo $CONDA_PREFIX
```

> [!NOTE] Check
> You are complete with this step when you can run `conda activate llm; python -c 'import boto3'` with no errors

*Back to [README.md](../README.md)*
