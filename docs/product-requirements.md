# HirePilot Product Requirements

## Product Summary

HirePilot is an AI career agent that continuously discovers, evaluates, researches, and prioritizes job opportunities for each user.

It is designed to reduce the amount of time users spend searching, researching, and deciding where to apply.

T.A.C.O.S. powers the intelligence behind HirePilot.

---

## Initial Target User

The first version is built for experienced professionals who are conducting an active job search and need help identifying the best opportunities quickly.

The initial target users include:

- Recruiters
- Talent Acquisition Leaders
- Technical Recruiters
- Recruiting Managers
- Directors and Heads of Talent
- Other experienced professionals with clearly defined career goals

HirePilot will eventually support a much broader audience, but the first version should solve one user group's problems extremely well.

---

## Core User Problems

Users currently have to:

- Search multiple job boards and company career pages
- Review duplicate job listings
- Research each company manually
- Determine whether a role is worth applying to
- Compare job requirements against their experience
- Track applications and follow-ups
- Find recruiters and hiring managers
- Write outreach messages
- Tailor resumes and application responses
- Monitor companies for new hiring activity

This process is fragmented, repetitive, and time-consuming.

---

## MVP Goal

The MVP should help a user answer:

> Which opportunities deserve my attention today, and what should I do next?

The MVP does not need to automate the entire job search.

It must reliably discover strong opportunities, explain why they matter, and recommend a clear next action.

---

## MVP User Flow

1. User creates a profile.
2. User uploads a resume.
3. User enters job preferences.
4. HirePilot discovers relevant jobs.
5. T.A.C.O.S. evaluates and ranks each opportunity.
6. HirePilot displays the strongest opportunities.
7. Each opportunity includes:
   - Match explanation
   - Company research
   - Risks and concerns
   - Recommended next action
8. User saves, dismisses, or pursues the opportunity.
9. HirePilot learns from the user's behavior.

---

## MVP Inputs

Each user should be able to provide:

- Resume
- Desired job titles
- Seniority level
- Preferred locations
- Remote, hybrid, or onsite preference
- Minimum compensation
- Preferred industries
- Preferred company stages
- Companies to follow
- Companies to avoid
- Required skills
- Optional skills
- Dealbreakers

---

## MVP Outputs

HirePilot should provide:

- Ranked job opportunities
- Opportunity Score
- Resume Match Score
- Company insights
- Hiring activity signals
- Job freshness
- Source information
- Duplicate detection
- Reasons to apply
- Reasons to be cautious
- Recommended outreach target
- Suggested next action
- Alerts for high-priority opportunities

---

## Opportunity Score

The Opportunity Score should evaluate more than resume fit.

It should consider:

- Resume alignment
- Seniority alignment
- Compensation fit
- Location fit
- Company growth
- Hiring activity
- Company stability
- Job freshness
- Applicant competition
- Recruiter accessibility
- User preferences
- Career growth potential
- Risk signals

The score must always include an explanation.

HirePilot should never show a score without explaining why the opportunity received that score.

---

## Company Intelligence

Each company profile should eventually include:

- Company overview
- Industry
- Company size
- Funding stage
- Funding history
- Growth signals
- Hiring trends
- Open roles
- Leadership changes
- Recruiters and talent leaders
- ATS platform
- Office locations
- Remote policy
- Recent news
- Stability signals
- Risk signals

Company intelligence should be reusable across all users.

---

## Job Discovery Requirements

HirePilot should discover jobs from as many legally and technically accessible sources as possible.

Priority sources include:

- Company career pages
- Greenhouse
- Lever
- Ashby
- Workday
- SmartRecruiters
- iCIMS
- Jobvite
- BambooHR
- Rippling
- Major job boards
- Startup job boards
- Remote job boards
- Industry-specific job boards
- Public search results
- Structured job posting data
- User-submitted sources

The system should track source health, source coverage, and last successful scan time.

---

## Deduplication Requirements

The same role may appear across multiple sources.

HirePilot should:

- Identify likely duplicates
- Merge duplicate records
- Preserve all source URLs
- Prefer the original company posting
- Track where each job was discovered
- Avoid notifying the user multiple times about the same role

---

## Personalization Requirements

HirePilot should learn from:

- Jobs the user saves
- Jobs the user dismisses
- Jobs the user applies to
- Companies the user follows
- Companies the user avoids
- Roles the user ignores
- Interview outcomes
- Offer outcomes
- Explicit preference changes

Learning should improve ranking without hiding important opportunities.

---

## AI Requirements

AI should be used for:

- Resume understanding
- Job requirement extraction
- Company research
- Opportunity explanation
- Risk identification
- Career fit analysis
- Recommended actions
- Outreach drafting
- Interview preparation
- Preference learning

AI should not invent facts.

Whenever possible, factual insights should include source information and confidence levels.

---

## Trust and Transparency

HirePilot should clearly distinguish between:

- Verified facts
- Inferred insights
- Estimates
- Opinions
- Missing information

Users should understand why a recommendation was made and how confident the system is.

---

## MVP Non-Goals

The first version will not include:

- Automatic job applications
- A native mobile application
- Full browser automation
- Social network scraping that violates platform rules
- Guaranteed coverage of every job on the internet
- Guaranteed interviews or offers
- Fully autonomous career decision-making

These may be evaluated later, but they should not delay the MVP.

---

## Primary Success Metric

The primary success metric is:

> The percentage of recommended opportunities that result in a meaningful user action.

Meaningful actions include:

- Saving the opportunity
- Applying
- Contacting a recruiter
- Requesting more research
- Preparing for an interview

---

## Secondary Success Metrics

- High-priority jobs discovered before major job boards
- Recommendation acceptance rate
- User time saved
- Duplicate reduction
- Alert engagement
- Application-to-interview conversion
- User retention
- Opportunity Score accuracy
- Source coverage and reliability

---

## Definition of MVP Success

The MVP is successful when a user can upload a resume, enter preferences, receive a ranked list of relevant opportunities, understand why each opportunity matters, and confidently decide what to do next.