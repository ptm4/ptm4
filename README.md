# Peter's Spellbook — Azure DevOps & Infrastructure-as-Code Portfolio

Production-grade Azure infrastructure, DevOps pipelines, and automation built and operated across a 20+ subscription enterprise environment.

This repo is my working portfolio — Terraform modules, Azure DevOps pipelines, and PowerShell tooling used to deploy and manage secure, private, hub-and-spoke Azure platforms.

> Environment: Azure (20+ subscriptions across hub / prod / test / dev / QA / UAT / lab), Azure DevOps (self-hosted agents), Entra ID workload-identity auth, centralized Terraform remote state (Azure Storage).
> Everything here was designed, built, and run by me in production.

---

## What This Repo Demonstrates

* End-to-end Azure infrastructure delivery using Terraform (networking → compute → application)
* Azure DevOps pipelines with Plan → Approval → Apply gates and workload identity auth
* Secure-by-default Azure design (private endpoints, private DNS, zero public exposure)
* Cross-subscription automation across a 20+ subscription hub-and-spoke environment
* Real production workloads (Front Door, Container Apps, WordPress, AMPLS, Policy)

---

## Key Projects

* **Fully Automated Homelab** — GitHub actions workflow to deploy docker-compose.yml from Desktop > Repo > Deploy to Homelab Server and compose > Run logging back to central fs & rotate logs every 15days 
* **Azure Front Door + Private Link (Terraform Modules)** — reusable system for onboarding new production sites
* **WordPress on Azure Container Apps** — fully private, production-ready platform with custom container + Key Vault integration
* **Custom Developed Internal Tool** - fully developed, custom internal tool for SQL writebacks to enable non-technical staff to make very controlled updates to a specific table to enable quicker turnaround on jobs*(see #11 below)*
* **Azure DevOps Pipelines** — standardized CI/CD for infrastructure with approval gates
* **Cross-Subscription Networking Automation (PowerShell)** — VNet, peering, DNS, and AMPLS automation, Network testing ACIs

---
## Table of Contents

1. [Terraform — AFD (Azure Front Door) Module Suite](#1-terraform--afd-azure-front-door-module-suite)
2. [Terraform — WordPress on Azure Container Apps (`wp-shccares`)](#2-terraform--wordpress-on-azure-container-apps)
3. [Terraform — ACI (Azure Container Instances) Testing Platform](#3-terraform--aci-testing-platform)
4. [Terraform — Policy Exemption Framework](#4-terraform--policy-exemption-framework)
5. [Terraform — CAE / Ubuntu VM Proof-of-Concepts](#5-terraform--cae--vm-proof-of-concepts)
6. [Azure DevOps Pipelines](#6-azure-devops-pipelines)
7. [PowerShell — Azure Networking Automation](#7-powershell--cross-subscription-networking-automation)
8. [PowerShell — Azure Pipelines (AMPLS + VNet Intake-Driven)](#8-powershell--azure-pipelines-ampls--vnet-intake)
9. [PowerShell — Azure Policy Automation](#9-powershell--azure-policy-automation)
10. [PowerShell — Azure & M365 Misc Utilities](#10-powershell--azure--m365-utilities)
11. [PowerShell WinForms App — GP Voucher Tool](#11-powershell-winforms-app--voucher-tool)
12. [Tech Stack Summary](#12-tech-stack-summary)

---

## 1. Terraform — AFD (Azure Front Door) Module Suite

**Path:** `Terraform/AFD/`

A reusable, pipeline-driven Terraform module system for onboarding new sites onto a shared Front Door profile. Each deployment uses a **Private Link Service (PLS) path** backed by an internal load balancer, abstracting the underlying networking so new sites can be onboarded with minimal input.

### What it builds

* Modular AFD deployments (origin groups, private origins, domains, WAF policies, routing)
* Private Link Service + internal load balancing stack
* Per-site deployment structure with parameterized configuration
* Optional WordPress-aware cache bypass rules
* Naming conventions derived from application input

### Intake automation

* PowerShell-based intake generator that produces an Excel workbook mapping directly to Terraform variables
* Includes validation guidance and shared configuration constants

### Documentation

* Step-by-step onboarding runbook (intake → pipeline → approval → validation → testing)
* Full mapping between input data and deployed resources

---

## 2. Terraform — WordPress on Azure Container Apps

**Path:** `Terraform/wp-shccares/`

End-to-end Terraform deployment of a **fully private WordPress platform on Azure Container Apps**, designed for secure production workloads with no public endpoints.

### Resources deployed

* Resource group, Log Analytics, and tagging governance
* Key Vault (RBAC, private endpoint)
* Storage (Premium file shares with private access)
* Azure Container Registry (private access via managed identity)
* MySQL Flexible Server (TLS enforced, private networking)
* Container App Environment (internal load balancer, private endpoint)
* Container App with mounted storage and Key Vault-integrated secrets

### Custom container image

* Based on official WordPress image with performance tuning (OPcache)
* Improved speed of Wordpress site for the main production site of the business by 2.5x by baking heavy plugins & media into custom docker image to avoid smb/io ops slowing & adding latency
* Custom entrypoint:

  * Generates and persists WordPress auth keys securely
  * Ensures plugin state persistence across deployments

### Operations

* Full production deployment runbook covering environment setup, pipeline integration, and cutover strategy

---

## 3. Terraform — ACI Testing Platform

**Path:** `Terraform/aci-module/`, `Terraform/ACI-vnet-testing/`

A multi-subscription ACI-based platform used for **network connectivity validation** across a hub-and-spoke environment.

* Reusable Terraform module with dynamic subscription targeting
* Containers running network diagnostic tools for port and connectivity testing
* Deployed across multiple environments for validation of NSGs, routing, and Private Endpoint DNS

---

## 4. Terraform — Policy Exemption Framework

**Path:** `Terraform/Policy/exemptions/`

Terraform-based framework for managing Azure Policy exemptions as code.

* Parameterized exemption definitions
* Scalable pattern using `for_each`
* Integrated into pipeline workflow with approval gates

---

## 5. Terraform — CAE / VM Proof-of-Concepts

**Path:** `Terraform/cae-*`, `Terraform/ubuntuvm-testing/`

* Early Container Apps + database deployment patterns used as a foundation for production builds
* Reusable Linux VM module with environment-specific configurations

---

## 6. Azure DevOps Pipelines

**Path:** `Terraform/Pipelines/`, `Azure/Pipelines/`

Standardized CI/CD pipelines for infrastructure and application delivery.

### Pattern

* Manual trigger → Plan → Approval → Apply
* Approval step with timeout and auto-reject
* Workload identity authentication
* Self-hosted agents
* Centralized remote state

### Capabilities

* Terraform deployments (modular + environment-based)
* Container image build and push workflows
* Parameterized infrastructure pipelines (e.g., networking, monitoring)
* Validation stages for input and environment readiness

---

## 7. PowerShell — Cross-Subscription Networking Automation

**Path:** `Azure/Networking/`

Automation scripts for managing networking across a multi-subscription Azure environment.

* VNet creation and subnet provisioning
* Hub/spoke peering automation
* Private DNS zone management and cleanup
* Resource discovery and inventory export
* CSV/Excel-driven deployment patterns

---

## 8. PowerShell — Azure Pipelines (AMPLS + VNet Intake)

**Path:** `Azure/Pipelines/`

Production deployment scripts used by CI/CD pipelines.

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

## 9. PowerShell — Azure Policy Automation

**Path:** `Azure/Policy/`

* Policy definition migration and normalization
* Bulk exemption handling (later replaced by Terraform framework)

---

## 10. PowerShell — Azure & M365 Utilities

**Path:** `Azure/Misc/`

Targeted automation scripts for operational tasks:

* RBAC role assignment
* Data transfer automation
* File structure migration
* Exchange Online management utilities

---

## 11. PowerShell WinForms App — Voucher Tool

**Path:** `GP-VoucherApp/`

A desktop application built with PowerShell for internal operations teams.

### Features

* Bulk processing of records via UI
* Secure SQL interaction using parameterized queries
* Dual authentication modes (Windows / SQL)
* Real-time logging and audit trail
* Packaged as a deployable executable

---

## 12. Tech Stack Summary

| Category                  | Tools / Services                                                                                       |
| ------------------------- | ------------------------------------------------------------------------------------------------------ |
| **IaC**                   | Terraform (AzureRM), HCL, remote state on Azure Storage, modular design                                |
| **Azure — Compute**       | Container Apps, ACI, Container Registry, Linux VMs                                                     |
| **Azure — Networking**    | VNets, hub-spoke peering, Private Endpoints, Private DNS, Front Door                                   |
| **Azure — Data**          | Storage Accounts (SMB), MySQL Flexible Server                                                          |
| **Security & Governance** | Entra ID, Key Vault, RBAC, Azure Policy, AMPLS                                                         |
| **Containers**            | Docker, custom images, runtime configuration                                                           |
| **CI/CD**                 | Azure DevOps pipelines, YAML, approval gates, self-hosted agents                                       |
| **Scripting**             | PowerShell, Azure CLI, automation tooling                                                              |
| **Desktop**               | PowerShell WinForms applications                                                                       |
| **Patterns**              | Hub-spoke networking, private-only architecture, cross-subscription automation, idempotent deployments |

---

## TL;DR

I'm **Peter Minerva**, an Azure-focused Infrastructure & DevOps Engineer.

This repo showcases real production work: Terraform modules, Azure DevOps pipelines, and PowerShell automation used to deploy and operate secure, private Azure environments at scale.

Everything here was designed, built, and operated by me.
