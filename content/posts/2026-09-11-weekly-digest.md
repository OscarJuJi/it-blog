---
title: "Digest: September 11, 2026"
date: 2026-09-11
description: "Engineers get Conductor 4.0, tsgolint v7, PlanetScale's 118M QPS benchmark, NVIDIA PAIR, ClickFix security threats, and Anthropic distillation findings."
tags:
  - digest
  - devtools
  - databases
  - security
---

This edition covers architectural upgrades in workflow orchestration, Go-powered linter performance, sharded database scale limits, local GPU routing, terminal-based security threats, and model distillation defense.

## [Netflix Conductor 4.0 Decouples Metadata to Scale Workflows 10x](https://www.infoq.com/news/2026/09/netflix-conductor-4-workflow/?utm_campaign=infoq_content&utm_source=infoq&utm_medium=feed&utm_term=global)

Netflix reworked its open-source Conductor workflow orchestration engine to Conductor 4.0 to support significantly larger enterprise workloads. The update separates workflow metadata from underlying task data, transitions evaluation steps to asynchronous background processing, and introduces dynamic worker allocation alongside granular concurrency controls. For software engineers building large-scale distributed systems, state management and synchronous evaluation loops frequently create performance bottlenecks as workflow complexity grows. These architecture changes allow Conductor to scale maximum workflow sizes tenfold from 2,500 to 30,000 tasks while cutting p99 evaluation latency by approximately 40 percent across 420 million monthly executions. In practice, teams running complex DAGs or long-lived orchestration pipelines should evaluate decoupling execution metadata from payload data and moving evaluation logic out of critical request paths to maintain predictable latency at scale.

*InfoQ*

## [tsgolint v7 Brings Native Go Type-Aware Linting to Oxlint](https://www.infoq.com/news/2026/09/tsgolint-oxlint-typescript/?utm_campaign=infoq_content&utm_source=infoq&utm_medium=feed&utm_term=global)

The tsgolint project released stable version v7, bringing native Go-powered type-aware linting capabilities to the Oxlint toolchain. The release relies on the typescript-go compiler to perform full semantic analysis for TypeScript 7.0.2 projects while delegating configuration and file discovery to Oxlint. Software engineers frequently struggle with slow CI/CD pipelines and lagging editor feedback caused by resource-heavy type-aware ESLint rules on large TypeScript codebases. By shifting semantic evaluation to Go, tsgolint supports 59 out of 61 standard type-aware lint rules with substantial speed improvements over traditional JavaScript-based linter setups. In practice, engineering teams can now adopt full type-aware static analysis across large frontend and backend TypeScript applications without suffering the severe build performance penalties typically associated with legacy linter configurations.

*InfoQ*

## [PlanetScale Benchmarks Neki Router at 118 Million Queries Per Second](https://planetscale.com/blog/118-million-queries-per-second-on-neki)

PlanetScale published performance benchmark results for its Neki platform preview, sustaining 118.5 million queries per second across 512 database shards holding 1.22 PiB of data. The test ran point-select queries by primary key against Postgres primary instances on r8g.16xlarge hardware routed through 480 Neki proxy instances for 16 minutes. Working developers designing high-throughput data layers need to understand the theoretical limits and latency characteristics of sharded database architectures under heavy read traffic. The benchmark demonstrated near-linear scaling from 5 to 512 shards, achieving a p99 latency of 6.06ms at the router level and 13.95ms at the client. In practice, while real-world workloads involve writes and multi-shard joins, these results confirm that stateless routing layers can scale read capacity predictably when database shards are strictly isolated.

*Hacker News*

## [ClickFix Terminal Command Scams Spread Across Windows and macOS](https://arstechnica.com/security/2026/09/clickfix-attacks-infecting-pcs-and-macs-are-going-viral/)

Cybersecurity researchers report that ClickFix attacks are rapidly spreading across compromised websites, targeting users on both Windows and macOS platforms. The attack mechanism displays a fake CAPTCHA overlay that prompts visitors to copy an obfuscated text string and paste it directly into Windows Run, PowerShell, or the macOS terminal. Developers and security teams must recognize that attackers are shifting away from resource-intensive malware delivery models like code-signed installers, relying instead on user execution to bypass OS protections like macOS Gatekeeper. Campaigns have utilized control infrastructure ranging from public Google Sheets to smart contracts, with thousands of compromised websites actively serving these fake prompts. In practice, security teams must educate users against pasting unknown terminal commands and implement endpoint policies that restrict unprivileged shell execution and monitor terminal invocations for suspicious copy-paste activity.

*Ars Technica*

## [NVIDIA Personal AI Router Distributes Inference Across Local Network GPUs](https://www.infoq.com/news/2026/09/nvidia-pair-ai-task-router/?utm_campaign=infoq_content&utm_source=infoq&utm_medium=feed&utm_term=global)

NVIDIA released the beta version of its Personal AI Router, a software tool that aggregates local network GPU inference capacity across multiple machines and distributes AI execution tasks. The tool specifically targets multi-agent development environments where simultaneous model calls easily exceed the processing bounds and VRAM of a single workstation GPU. Engineers building agentic software pipelines locally often face hardware bottlenecks when running multiple autonomous models in parallel during development and testing. By pooling local network compute resources, the router balances inference requests across available machines without requiring cloud infrastructure. In practice, developers working with local multi-agent workflows can now harness idle hardware across their local network to run concurrent agent loops without paying external API costs or redesigning model execution code.

*InfoQ*

## [Anthropic Exposes Chain-of-Thought Distillation Tactics Used Against AI Models](https://techcrunch.com/2026/09/10/anthropic-details-distillation-campaigns-from-alibaba-moonshot-ai-and-deepseek/)

Anthropic published an analysis detailing persistent distillation campaigns by rival AI labs, documenting nearly 200 million API interactions aimed at harvesting proprietary model capabilities. The report highlights methods used by organizations like Alibaba, Moonshot AI, and DeepSeek, which bypassed model safeguards using techniques such as asking Claude to translate its internal working memory into katakana. Developers building LLM-backed applications and APIs must understand how prompt injection and systemic distillation attempts exploit prompt boundaries to exfiltrate proprietary reasoning logic and internal system instructions. The largest campaign alone generated 151 million requests across 3,500 accounts to extract training data for Alibaba's Qwen models. In practice, teams exposing AI interfaces must implement advanced rate-limiting, detect prompt framing tricks that request memory translation, and monitor API traffic for automated chain-of-thought extraction patterns.

*TechCrunch*

*Selected and summarized automatically from the sources linked above.*
