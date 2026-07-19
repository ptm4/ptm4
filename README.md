# Peter's Spellbook

Azure Infrastructure-as-Code, DevOps automation, and a homelab playground.

This repo has two halves, and they should be read differently:

* **[infra/](infra/)** is my professional work: production-grade Terraform, Azure DevOps pipelines, and PowerShell tooling that I designed, built, and operate across a 20+ subscription enterprise Azure environment. It has been de-sensitized (names, IDs, and secrets stripped) for public viewing, but the engineering is the real thing.
* **[homelab/](homelab/)** is my personal playground. Everything in it is a hobby project, and it doubles as my lab for agentic coding: building the skills, rules, and harnesses that govern what AI agents can do, then letting them do real work against real machines and learning from how those structures hold up.

That split is intentional. If you're evaluating my engineering, start with `infra/`. If you're a hobbyist tinkerer, `homelab/` will feel familiar; it's a lab, breaking things there is part of the point, so judge it gently.

> Professional environment: Azure (20+ subscriptions across hub / prod / test / dev / QA / UAT / lab), Azure DevOps with self-hosted agents, Entra ID workload-identity auth, centralized Terraform remote state on Azure Storage.

---

## Table of Contents

**infra/**
1. [Terraform: AFD Module Suite](#1-terraform-afd-module-suite)
2. [Terraform: WordPress on Azure Container Apps](#2-terraform-wordpress-on-azure-container-apps)
3. [Terraform: ACI Testing Platform](#3-terraform-aci-testing-platform)
4. [Terraform: Policy Exemption Framework](#4-terraform-policy-exemption-framework)
5. [Terraform: VM Proof-of-Concepts](#5-terraform-vm-proof-of-concepts)
6. [Azure DevOps Pipelines](#6-azure-devops-pipelines)
7. [PowerShell: Cross-Subscription Networking Automation](#7-powershell-cross-subscription-networking-automation)
8. [PowerShell: AMPLS + VNet Pipeline Scripts](#8-powershell-ampls--vnet-pipeline-scripts)
9. [PowerShell: Azure Policy Automation](#9-powershell-azure-policy-automation)
10. [PowerShell: Azure & M365 Utilities](#10-powershell-azure--m365-utilities)
11. [PowerShell WinForms App: GP Voucher Tool](#11-powershell-winforms-app-gp-voucher-tool)
12. [Tech Stack Summary](#12-tech-stack-summary)

**homelab/**

13. [The Playground](#13-homelab-the-playground)

---

## infra/: Production Azure Engineering

What this half demonstrates:

* End-to-end Azure infrastructure delivery with Terraform (networking, then compute, then application)
* Azure DevOps pipelines with Plan, Approval, and Apply gates using workload identity auth
* Secure-by-default design: private endpoints, private DNS, no public exposure
* Cross-subscription automation across a hub-and-spoke environment
* Real production workloads: Front Door, Container Apps, WordPress, AMPLS, Azure Policy

Key results this tooling delivered in production:

* Onboarded **32 IIS-hosted sites and APIs** onto Front Door with Private Link origins using the AFD module suite and its intake pipeline
* Re-platformed the company's externally hosted production WordPress site onto Container Apps with fully private networking, cutting server response times from ~4s to ~100ms by baking heavy plugins into a custom Docker image instead of loading them over SMB
* Replaced click-ops networking with idempotent, intake-driven VNet, peering, DNS, and AMPLS automation

---

## 1. Terraform: AFD Module Suite

**Path:** [infra/Terraform/AFD/](infra/Terraform/AFD/) (has its own [README](infra/Terraform/AFD/README.md))

A reusable, pipeline-driven Terraform module system for onboarding new sites onto a shared Front Door profile. Each deployment uses a Private Link Service path backed by an internal load balancer, abstracting the underlying networking so new sites can be onboarded with minimal input.

### What it builds

* Modular AFD deployments: origin groups, private origins, domains, WAF policies, routing
* Private Link Service + internal load balancing stack
* Per-site deployment structure with parameterized configuration
* Optional WordPress-aware cache bypass rules
* Naming conventions derived from application input

### Intake automation

* PowerShell intake generator ([New-AFDSiteIntake.ps1](infra/Terraform/AFD/New-AFDSiteIntake.ps1)) that produces an Excel workbook mapping directly to Terraform variables
* Includes validation guidance and shared configuration constants

### Documentation

* Step-by-step onboarding runbook (intake, pipeline, approval, validation, testing)
* Full mapping between input data and deployed resources

---

## 2. Terraform: WordPress on Azure Container Apps

**Path:** [infra/Terraform/wp-jammylab/](infra/Terraform/wp-jammylab/)

End-to-end Terraform deployment of a fully private WordPress platform on Azure Container Apps, built for a production workload with no public endpoints. Sanitized here; the production twin runs the main public site of the business.

### Resources deployed

* Resource group, Log Analytics, and tagging governance
* Key Vault (RBAC, private endpoint)
* Storage (Premium file shares with private access)
* Azure Container Registry (private access via managed identity)
* MySQL Flexible Server (TLS enforced, private networking)
* Container App Environment (internal load balancer, private endpoint)
* Container App with mounted storage and Key Vault-integrated secrets

### Custom container image

* Based on the official WordPress image with performance tuning (OPcache)
* Diagnosed slow page loads as plugin I/O over SMB, then baked heavy plugins and media into the image; server response times went from ~4s to ~100ms
* Custom entrypoint that generates and persists WordPress auth keys securely and keeps plugin state consistent across deployments

### Operations

* Full production deployment runbook ([ProdDeployment.md](infra/Terraform/wp-jammylab/ProdDeployment.md)) covering environment setup, pipeline integration, and cutover strategy

---

## 3. Terraform: ACI Testing Platform

**Paths:** [infra/Terraform/aci-module/](infra/Terraform/aci-module/), [infra/Terraform/ACI-vnet-testing/](infra/Terraform/ACI-vnet-testing/), [infra/Terraform/aci-prod-it/](infra/Terraform/aci-prod-it/)

A multi-subscription ACI-based platform used for network connectivity validation across the hub-and-spoke environment.

* Reusable Terraform module with dynamic subscription targeting
* Containers running network diagnostic tools for port and connectivity testing
* Deployed across multiple environments to validate NSGs, routing, and Private Endpoint DNS

---

## 4. Terraform: Policy Exemption Framework

**Path:** [infra/Terraform/Policy/](infra/Terraform/Policy/)

Terraform-based framework for managing Azure Policy exemptions as code.

* Parameterized exemption definitions
* Scalable pattern using `for_each`
* Integrated into the pipeline workflow with approval gates

---

## 5. Terraform: VM Proof-of-Concepts

**Path:** [infra/Terraform/ubuntuvm-testing/](infra/Terraform/ubuntuvm-testing/)

* Reusable Linux VM module with per-environment `.tfvars` configurations (dev, test, and multiple prod workloads)
* Early Container Apps + database deployment patterns from this work became the foundation for the production WordPress build

---

## 6. Azure DevOps Pipelines

**Paths:** [infra/Terraform/Pipelines/](infra/Terraform/Pipelines/), [infra/Azure/Pipelines/](infra/Azure/Pipelines/)

Standardized CI/CD for infrastructure and application delivery.

### Pattern

* Manual trigger, then Plan, then Approval, then Apply
* Approval step with timeout and auto-reject
* Workload identity authentication
* Self-hosted agents
* Centralized remote state

### Capabilities

* Terraform deployments (modular and environment-based)
* Container image build and push workflows
* Parameterized infrastructure pipelines (networking, monitoring)
* Validation stages for input and environment readiness

---

## 7. PowerShell: Cross-Subscription Networking Automation

**Path:** [infra/Azure/Networking/](infra/Azure/Networking/)

Automation for managing networking across a multi-subscription Azure environment.

* VNet creation and subnet provisioning ([createVNet.ps1](infra/Azure/Networking/createVNet.ps1))
* Hub/spoke peering automation ([azvnetpeering.ps1](infra/Azure/Networking/azvnetpeering.ps1), [peerdeploy.ps1](infra/Azure/Networking/peerdeploy.ps1))
* Private DNS zone management and cleanup ([PrivateDNS.ps1](infra/Azure/Networking/PrivateDNS.ps1), [VnetLinkCleanup.ps1](infra/Azure/Networking/VnetLinkCleanup.ps1))
* Resource discovery and inventory export
* CSV/Excel-driven deployment patterns

---

## 8. PowerShell: AMPLS + VNet Pipeline Scripts

**Path:** [infra/Azure/Pipelines/](infra/Azure/Pipelines/)

Production deployment scripts executed by CI/CD pipelines.

### AMPLS deployment

* End-to-end deployment of Azure Monitor Private Link Scope
* Cross-subscription DNS zone management
* Scoped resource linking (Log Analytics, App Insights, etc.)
* Fully idempotent execution

### VNet deployment

* Excel-driven deployment workflow
* Validation, grouping, and conditional deployment logic
* Automated hub connectivity and peering

---

## 9. PowerShell: Azure Policy Automation

**Path:** [infra/Azure/Policy/](infra/Azure/Policy/)

* Policy definition migration and normalization
* Bulk exemption handling (later replaced by the Terraform framework in section 4)

---

## 10. PowerShell: Azure & M365 Utilities

**Path:** [infra/Azure/Misc/](infra/Azure/Misc/)

Targeted automation for operational tasks:

* RBAC role assignment ([GroupRBACAssign.ps1](infra/Azure/Misc/GroupRBACAssign.ps1))
* Data transfer automation ([azcopy.ps1](infra/Azure/Misc/azcopy.ps1))
* File structure migration
* Exchange Online management utilities

---

## 11. PowerShell WinForms App: GP Voucher Tool

**Path:** [infra/GP-VoucherApp/](infra/GP-VoucherApp/)

A desktop application built with PowerShell WinForms for internal operations teams: it gives non-technical staff a controlled way to write back to a specific SQL table, cutting job turnaround time without opening up direct database access.

* Bulk processing of records via UI
* Secure SQL interaction using parameterized queries
* Dual authentication modes (Windows / SQL)
* Real-time logging and audit trail
* Packaged as a deployable executable

---

## 12. Tech Stack Summary

| Category                  | Tools / Services                                                                                        |
| ------------------------- | ------------------------------------------------------------------------------------------------------ |
| **IaC**                   | Terraform (AzureRM), HCL, remote state on Azure Storage, modular design                                 |
| **Azure Compute**         | Container Apps, ACI, Container Registry, Linux VMs                                                      |
| **Azure Networking**      | VNets, hub-spoke peering, Private Endpoints, Private DNS, Front Door, Private Link Service              |
| **Azure Data**            | Storage Accounts (SMB), MySQL Flexible Server                                                           |
| **Security & Governance** | Entra ID, Key Vault, RBAC, Azure Policy, AMPLS                                                          |
| **Containers**            | Docker, custom images, runtime configuration                                                            |
| **CI/CD**                 | Azure DevOps pipelines, YAML, approval gates, self-hosted agents                                        |
| **Scripting**             | PowerShell, Azure CLI, automation tooling                                                               |
| **Desktop**               | PowerShell WinForms applications                                                                        |
| **Patterns**              | Hub-spoke networking, private-only architecture, cross-subscription automation, idempotent deployments  |

---

## 13. homelab/: The Playground

Everything in [homelab/](homelab/) is a personal project. It runs my actual home infrastructure, and it is deliberately where I practice agentic coding: I build the structures around the agents (skills that package repeatable procedures, rules that bound what they may touch, harnesses that let them act against real machines safely) and then put them to work. The output matters less than what the structure teaches me. Hobbyist tinkerers will understand. Don't judge harshly.

What's in it:

* **[RPI-srv/](homelab/RPI-srv/)**: Raspberry Pi services. Discord bots (weather, sports, CS2/HLTV, Jellyfin, health digest), a Node.js web control panel for managing the fleet, and a notes app.
* **[noblenumbat-srv/](homelab/noblenumbat-srv/)**: media server stack (Docker Compose) plus a self-healing VPN watchdog ([vpn-stack-heal.sh](homelab/noblenumbat-srv/yams/vpn-stack-heal.sh)) that detects dead port forwarding and recovers the stack unattended.
* **[Tools/](homelab/Tools/)**: fleet tooling. Health checks across hosts ([homelab-doctor](homelab/Tools/homelab/homelab-doctor.py)), network reporting, systemd timers for unattended updates and reboots, a CS2 stats coach built on the Leetify API, and other experiments.
* **[PTMonitor-widget/](homelab/PTMonitor-widget/)**: a desktop monitoring widget built with Tauri.
* **[homelab-techdoc.md](homelab/homelab-techdoc.md)** and draw.io diagrams: architecture documentation for all of it.

Deployment is automated end to end: pushing a `docker-compose.yml` change to this repo triggers a GitHub Actions workflow that deploys to the homelab servers, brings the stack up, and logs back to a central filesystem with 15-day rotation.

---

## TL;DR

I'm **Peter Minerva**, an Azure-focused Infrastructure & DevOps Engineer.

`infra/` is my professional portfolio: Terraform modules, Azure DevOps pipelines, and PowerShell automation that deploy and operate secure, private Azure environments at scale. Designed, built, and run by me in production.

`homelab/` is where I tinker, and where AI agents earn their keep under rules I write.
