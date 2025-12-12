# Deployment Permissions Issue

## Current Error
```
PERMISSION_DENIED: The caller does not have permission
```

## Required Permissions

To deploy to Cloud Run, you need one of these IAM roles:

### Option 1: Cloud Run Admin (Recommended)
```bash
gcloud projects add-iam-policy-binding maxprint-479504 \
  --member="user:chris.la.williamson@gmail.com" \
  --role="roles/run.admin"
```

### Option 2: Owner (Full Access)
```bash
gcloud projects add-iam-policy-binding maxprint-479504 \
  --member="user:chris.la.williamson@gmail.com" \
  --role="roles/owner"
```

### Option 3: Multiple Roles (Minimum Required)
```bash
# Cloud Build Editor
gcloud projects add-iam-policy-binding maxprint-479504 \
  --member="user:chris.la.williamson@gmail.com" \
  --role="roles/cloudbuild.builds.editor"

# Cloud Run Admin
gcloud projects add-iam-policy-binding maxprint-479504 \
  --member="user:chris.la.williamson@gmail.com" \
  --role="roles/run.admin"

# Service Account User
gcloud projects add-iam-policy-binding maxprint-479504 \
  --member="user:chris.la.williamson@gmail.com" \
  --role="roles/iam.serviceAccountUser"

# Storage Admin (for Cloud Build artifacts)
gcloud projects add-iam-policy-binding maxprint-479504 \
  --member="user:chris.la.williamson@gmail.com" \
  --role="roles/storage.admin"
```

## Who Can Grant Permissions?

Only project owners/admins can grant these permissions. If you're not a project owner:

1. Ask a project owner to run the commands above
2. Or use the [GCP Console](https://console.cloud.google.com/iam-admin/iam?project=maxprint-479504)

## Alternative: Use Service Account

If you can't get user permissions, you can use a service account:

1. Create a service account with the necessary roles
2. Download the key
3. Authenticate: `gcloud auth activate-service-account`

## After Granting Permissions

Wait a few minutes for permissions to propagate, then retry:

```bash
./deploy-backend.sh maxprint-479504
```

## Check Current Permissions

```bash
gcloud projects get-iam-policy maxprint-479504 \
  --flatten="bindings[].members" \
  --format="table(bindings.role)" \
  --filter="bindings.members:chris.la.williamson@gmail.com"
```



