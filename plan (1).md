# Email Automation System: Implementation Plan

## 1. System Overview
This document outlines the architecture and workflow for a low-volume, highly personalized email automation system. The system integrates with an existing CSV-based contact ingestion pipeline, dynamically generates unique email content, and schedules dispatch across multiple sending accounts while strictly adhering to anti-spam heuristics.

## 2. Phase 1: Data Ingestion & Processing
*   **CSV Integration Pipeline:** Establish a continuous connection with the existing business contact extraction system.
*   **Data Parsing & Sanitization:** Automatically ingest new CSV files, extract required fields (e.g., Business Name, Decision Maker Name, Context), and filter out invalid or malformed email addresses.
*   **Queue Management:** Load the sanitized contacts into a dispatch queue, assigning them sequentially to the 5 active sending accounts.

## 3. Phase 2: Dynamic Content Generation (The Claude Integration)
To maintain an absolute zero-complaint rate and avoid algorithmic fingerprinting, the system will utilize automated content generation, similar to the dynamic text generation pipelines built in previous automation systems. 
*   **Claude API Integration:** Route the parsed contact data (from Phase 1) through Claude.
*   **Prompt Engineering for Variance:** Instruct Claude to rewrite the core value proposition for every single email. It must generate unique subject lines, varied opening hooks, and distinct phrasing for each prospect.
*   **Output Validation:** Ensure Claude's output remains plain-text, professional, and strictly avoids spam-triggering keywords before moving the message to the outbox.

## 4. Phase 3: Dispatch & Scheduling Logic
*   **Account Rotation:** Distribute the daily sending load evenly across the 5 source accounts (targeting 5 emails per account initially).
*   **Algorithmic Jittering:** Implement randomized time delays between dispatches. The system must never send emails on a predictable loop. Delays should randomly vary between 15 and 90 minutes during standard business hours.
*   **Volume Caps:** Enforce a hard stop at the daily quota limit to ensure the accounts remain protected from automated rate-limit flags.

## 5. Phase 4: Monitoring & Analytics
*   **Delivery Tracking:** Log successful dispatches and immediate bounces.
*   **Account Health Checks:** Implement periodic pauses to review the standing of the 5 sending accounts and ensure no unusual activity flags have been raised.
*   **Feedback Loop:** Use reply rates to adjust Claude's generation prompts over time, optimizing for the highest engagement patterns.
