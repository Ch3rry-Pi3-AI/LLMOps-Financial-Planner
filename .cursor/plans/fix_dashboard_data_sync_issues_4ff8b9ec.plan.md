---
name: Fix Dashboard Data Sync Issues
overview: "Fix three dashboard issues: asset allocation display, last analysis timestamp, and actual vs target allocation visibility. All fixes are code-only changes requiring backend and frontend redeployment, with no Terraform infrastructure changes needed."
todos:
  - id: backend-code-update
    content: Update backend/api/main.py to ensure positions endpoint returns fresh instrument data
    status: pending
  - id: frontend-jobs-api
    content: Add /api/jobs fetching in dashboard.tsx to populate Last Analysis date
    status: pending
  - id: frontend-actual-vs-target
    content: Display actual vs target allocations in User Settings section
    status: pending
  - id: backend-package
    content: Package backend API Lambda with docker (uv run package_docker.py)
    status: pending
    dependencies:
      - backend-code-update
  - id: backend-deploy
    content: Deploy updated Lambda code to AWS (aws lambda update-function-code)
    status: pending
    dependencies:
      - backend-package
  - id: frontend-build
    content: Build frontend production bundle (npm run build)
    status: pending
    dependencies:
      - frontend-jobs-api
      - frontend-actual-vs-target
  - id: frontend-deploy
    content: Deploy frontend to S3 and invalidate CloudFront (uv run deploy.py)
    status: pending
    dependencies:
      - frontend-build
      - backend-deploy
  - id: test-verification
    content: "Test all three fixes: asset allocation chart, last analysis date, actual vs target display"
    status: pending
    dependencies:
      - frontend-deploy
---

# Fix Dashboard Data Synchronization Issues

## Overview

We've identified three issues preventing the dashboard from displaying accurate portfolio data after analysis. All fixes involve code changes only - **no Terraform infrastructure modifications required**. We'll update the backend API and frontend React code, then redeploy both.

## Issues Summary

1. **Asset Allocation Chart Shows Only Cash** - Instruments lack allocation data that should be populated by Tagger agent
2. **Last Analysis Always "Never"** - Dashboard doesn't fetch job completion data
3. **Slider Bars Don't Reflect Portfolio** - Only show targets, not actual allocations (UX confusion)

---

## Proposed Fixes

### Fix 1: Ensure Fresh Instrument Data in Positions Endpoint

**Problem**: When the dashboard refreshes after analysis, the positions endpoint may return stale instrument data that hasn't been updated by the Tagger agent yet.

**Solution**: Modify the positions endpoint to always fetch the latest instrument data directly from the database, ensuring any recent updates from the Tagger agent are included.

**File**: [`backend/api/main.py`](backend/api/main.py)

**Changes**:

- In the `list_positions` endpoint (around line 760-766), ensure we're fetching instrument data fresh from the database for each position
- Verify the `db.instruments.find_by_symbol()` call returns complete allocation data
- Add logging to confirm allocation data is present

**Justification**: The Tagger agent updates instruments during analysis (Step 1 of orchestration). By explicitly fetching fresh instrument data when returning positions, we ensure the dashboard sees the newly populated allocations.

---

### Fix 2: Implement Last Analysis Date Fetching

**Problem**: Dashboard has a placeholder that always sets `lastAnalysisDate` to `null` (line 281 of dashboard.tsx).

**Solution**: Call the existing `/api/jobs` endpoint to fetch recent jobs and extract the most recent completed job's timestamp.

**File**: [`frontend/pages/dashboard.tsx`](frontend/pages/dashboard.tsx)

**Changes**:

1. Add API call in the initial `loadData()` function (after user sync)
2. Fetch jobs from `/api/jobs` endpoint (already exists in backend)
3. Filter for `status === 'completed'` jobs
4. Sort by `completed_at` and extract the most recent
5. Set `lastAnalysisDate` state with this timestamp
6. Also update in the `handleAnalysisCompleted` event listener

**Code snippet to add**:

```typescript
// After fetching user data, fetch recent jobs
const jobsResponse = await fetch(`${API_URL}/api/jobs`, {
  headers: { Authorization: `Bearer ${token}` },
});

if (jobsResponse.ok) {
  const jobsData = await jobsResponse.json();
  const completedJobs = jobsData.jobs.filter(
    (job: any) => job.status === 'completed' && job.completed_at
  );
  
  if (completedJobs.length > 0) {
    // Jobs are already sorted by created_at desc from backend
    const mostRecent = completedJobs[0];
    setLastAnalysisDate(mostRecent.completed_at);
  }
}
```

**Justification**: The backend already provides this data via the `/api/jobs` endpoint (lines 1173-1210 of main.py). We simply need to consume it on the frontend.

---

### Fix 3: Display Actual vs Target Allocations

**Problem**: Users see target allocation sliders but not their actual portfolio composition, causing confusion about whether the sliders "do anything."

**Solution**: Enhance the UI to show both target (from user settings) and actual (from positions) allocations side-by-side.

**File**: [`frontend/pages/dashboard.tsx`](frontend/pages/dashboard.tsx)

**Changes**:

1. Use the existing `calculatePortfolioSummary()` function to get actual allocations
2. Display actual allocation percentages alongside targets in the settings section
3. Add visual indicators (colors) to show alignment/misalignment with targets
4. Update the mini pie charts to show both target and actual as separate segments or concentric rings

**Example UI enhancement**:

```typescript
<div className="space-y-3">
  <div>
    <label className="text-sm text-gray-600">
      Equity: {equityTarget}% (Target) | {actualEquityPercent}% (Actual)
    </label>
    <input type="range" ... />
  </div>
  {/* Add visual indicator if off-target */}
  {Math.abs(equityTarget - actualEquityPercent) > 5 && (
    <p className="text-xs text-amber-600">
      ⚠️ Portfolio is {actualEquityPercent - equityTarget > 0 ? 'over' : 'under'}weighted
    </p>
  )}
</div>
```

**Justification**: The sliders DO serve a purpose (agents use these targets for recommendations), but users can't see this without showing the comparison. This maintains existing functionality while adding clarity.

---

## Deployment Plan

### Prerequisites

- Docker Desktop running (for Lambda packaging)
- AWS CLI configured
- Access to the deployed infrastructure

### Step 1: Update and Deploy Backend API Lambda

**Why first?**: Backend changes ensure the positions endpoint returns correct data before the frontend expects it.

**Commands**:

```bash
# Navigate to backend/api directory
cd backend/api

# Package the Lambda function with Docker
uv run package_docker.py

# This creates api_lambda.zip with latest code
# Expected output: "✅ Created api_lambda.zip"
```

**Update the Lambda function**:

```bash
# Deploy the updated package to AWS
aws lambda update-function-code \
  --function-name alex-api \
  --zip-file fileb://api_lambda.zip

# Wait for update to complete
aws lambda wait function-updated \
  --function-name alex-api

# Expected output: Function updated successfully
```

**Verify deployment**:

```bash
# Check function configuration
aws lambda get-function-configuration \
  --function-name alex-api \
  --query 'LastModified'

# Should show current timestamp
```

**Estimated time**: 3-5 minutes

---

### Step 2: Update and Deploy Frontend

**Why second?**: Frontend can now safely consume the corrected backend data.

**Commands**:

```bash
# Navigate to frontend directory
cd ../../frontend

# Rebuild the production frontend
npm run build

# This creates optimized build in /out directory
# Expected output: "✓ Compiled successfully"
```

**Deploy to S3 and invalidate CloudFront**:

```bash
# Navigate to scripts directory
cd ../scripts

# Deploy frontend to S3 and invalidate CDN cache
uv run deploy.py

# This script:
# 1. Uploads all files from frontend/out to S3
# 2. Sets correct content types
# 3. Creates CloudFront invalidation
# 4. Waits for invalidation to complete

# Expected output:
# "✅ Frontend deployed to S3"
# "✅ CloudFront invalidation created: [ID]"
# "⏳ Waiting for invalidation to complete..."
# "✅ CloudFront cache invalidated successfully"
```

**Estimated time**: 3-5 minutes

---

### Step 3: Test the Fixes

**Test Sequence**:

1. **Clear browser cache** (important for CloudFront updates)

   - Chrome: Ctrl+Shift+Delete → "Cached images and files"
   - Or use incognito/private window

2. **Access your CloudFront URL**
   ```
   https://[your-cloudfront-id].cloudfront.net/dashboard
   ```

3. **Verify Fix 1 (Asset Allocation)**:

   - Navigate to Accounts page
   - Ensure you have positions in your accounts
   - Go to Advisor Team → Start New Analysis
   - Wait for analysis to complete (~90 seconds)
   - Return to Dashboard
   - **Expected**: Asset Allocation chart shows actual breakdown (not just cash)

4. **Verify Fix 2 (Last Analysis)**:

   - After analysis completes
   - Check Dashboard
   - **Expected**: "Last Analysis" shows actual date (e.g., "Dec 12, 2025")

5. **Verify Fix 3 (Actual vs Target)**:

   - Scroll to User Settings section
   - **Expected**: See both target and actual percentages displayed
   - Try moving sliders
   - **Expected**: Can see how current portfolio compares to targets

---

## Terraform Infrastructure Impact

### ✅ No Terraform Changes Required

**Analysis**:

All three fixes involve only application code changes:

- Backend API Lambda code (`backend/api/main.py`) - logic changes only
- Frontend React code (`frontend/pages/dashboard.tsx`) - UI changes only

No infrastructure components are affected:

- ✅ Lambda function configuration (memory, timeout, env vars) - unchanged
- ✅ API Gateway routes and methods - unchanged
- ✅ CloudFront distribution settings - unchanged
- ✅ S3 bucket configuration - unchanged
- ✅ Database schema - unchanged
- ✅ IAM permissions - unchanged

**Conclusion**: We only need to redeploy the application code, not the infrastructure.

---

## Rollback Plan

If any issues arise after deployment:

### Backend Rollback

```bash
# Restore previous Lambda version
aws lambda update-function-code \
  --function-name alex-api \
  --zip-file fileb://api_lambda_backup.zip
```

### Frontend Rollback

```bash
# Re-run deploy script with previous build
cd frontend
git checkout HEAD~1  # Get previous version
npm run build
cd ../scripts
uv run deploy.py
```

---

## Post-Deployment Monitoring

**Check CloudWatch Logs**:

```bash
# Monitor API Lambda for errors
aws logs tail /aws/lambda/alex-api --follow

# Look for any errors in dashboard data loading
```

**Verify in AWS Console**:

1. Lambda Console → alex-api → Monitor tab → Recent invocations
2. CloudFront Console → Your distribution → Monitoring → Check cache hit ratio

---

## Expected Outcomes

After successful deployment:

1. ✅ **Asset allocation chart displays real data** - Shows equity, bonds, etc., not just cash
2. ✅ **Last analysis shows timestamp** - Updates after each analysis run
3. ✅ **User settings show context** - Displays actual vs target allocations for better understanding

**Total estimated time**: 10-15 minutes (excluding analysis run time for testing)