# Trello Webhook Setup Guide

This guide walks you through setting up the webhook callback URL and registering it with Trello.

## Step 1: Get Your Cloud Run Service URL

Your backend is deployed to Cloud Run with the service name `trello-orders-api`.

### Option A: If Already Deployed

Get your current service URL:

```bash
gcloud run services describe trello-orders-api \
  --region us-central1 \
  --project maxprint-479504 \
  --format 'value(status.url)'
```

This will output something like:
```
https://trello-orders-api-xxxxx-uc.a.run.app
```

**Note**: Your actual service URL may differ. Use the `gcloud` command above to get the current URL.

### Option B: If Not Yet Deployed

Deploy your backend first:

```bash
./deploy-backend.sh maxprint-479504 trello-orders-api us-central1
```

The script will output the service URL at the end.

## Step 2: Construct Your Webhook Callback URL

Your webhook endpoint is at `/trello/webhook`, so your full callback URL will be:

```
https://trello-orders-api-xxxxx-uc.a.run.app/trello/webhook
```

Replace `xxxxx` with your actual service URL from Step 1.

## Step 3: Set Environment Variable

Add the webhook callback URL to your `.env` file:

```bash
# In your project root .env file
TRELLO_WEBHOOK_CALLBACK_URL=https://trello-orders-api-903041792182.us-central1.run.app/trello/webhook
```

**Note**: Replace with your actual service URL from Step 1.

**Important**: Also set this as an environment variable in Cloud Run so the deployed service can use it:

```bash
gcloud run services update trello-orders-api \
  --region us-central1 \
  --project maxprint-479504 \
  --update-env-vars TRELLO_WEBHOOK_CALLBACK_URL=https://trello-orders-api-903041792182.us-central1.run.app/trello/webhook
```

## Step 4: Verify Webhook Endpoint is Accessible

Before registering, test that your endpoint responds:

```bash
# Test HEAD request (Trello uses this for verification)
curl -I https://trello-orders-api-903041792182.us-central1.run.app/trello/webhook

# Should return: HTTP/2 200
```

If you get a 200 response, the endpoint is ready!

## Step 5: Register Webhook with Trello

Now register the webhook for the Bourquin board:

```bash
cd backend
python register_bourquin_webhook.py
```

This will:
1. Check that `TRELLO_WEBHOOK_CALLBACK_URL` is set
2. Register a webhook for board ID `64df710946c4c9a25a0f9bd5` (Bourquin Signs)
3. Output the webhook ID for your records

## Step 6: Verify Webhook is Active

List your webhooks to confirm:

```bash
cd backend
python trello_webhook_cli.py list
```

You should see your new webhook with `active=true`.

## Step 7: Test the Webhook

1. Make a change in the Bourquin Trello board (e.g., create a card, move a card to a different list)
2. Check your Cloud Run logs:

```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=trello-orders-api" \
  --limit 50 \
  --format json \
  --project maxprint-479504
```

Look for log entries like:
- `trello_webhook_received` - Webhook was received
- `Processing event` - Event is being processed
- `Successfully processed createCard` - Card extraction completed

3. Verify data in BigQuery:

```sql
-- Check recent events
SELECT * 
FROM `maxprint-479504.trello_rag.trello_webhook_events`
ORDER BY action_date DESC
LIMIT 10;

-- Check if cards were created
SELECT * 
FROM `maxprint-479504.trello_rag.bourquin_cards_current`
ORDER BY datetime_created DESC
LIMIT 10;
```

## Troubleshooting

### Webhook Not Receiving Events

1. **Check webhook is active:**
   ```bash
   cd backend
   python trello_webhook_cli.py list
   ```

2. **Check endpoint is accessible:**
   ```bash
   curl -I https://trello-orders-api-903041792182.us-central1.run.app/trello/webhook
   ```
   Should return `HTTP/2 200`

3. **Check Cloud Run logs for errors:**
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=trello-orders-api AND severity>=ERROR" \
     --limit 20 \
     --project maxprint-479504
   ```

### Common Issues

- **502 Bad Gateway when registering**: Trello's API may be experiencing issues. Check https://trello.status.atlassian.com/ and retry later.
- **Webhook not receiving events**: Verify the webhook is active and the callback URL is publicly accessible.
- **Permission errors**: Ensure your Trello token has access to the board you're registering webhooks for.

## Next Steps

Once webhooks are working:

1. ✅ Events are being stored in `trello_webhook_events`
2. ✅ New cards are being extracted and stored in `bourquin_cards_current`
3. ✅ Line items are being extracted and stored in `bourquin_lineitems_current`
4. ✅ Card updates trigger re-extraction when description changes

You can now query the data for analytics and insights!
