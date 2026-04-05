# trmnl-calendar

Updating the ICS calendar URLs used by the lambda requires updating a parameter in SSM:

```shell
aws ssm put-parameter \
  --name /trmnl-calendar/ics-urls \
  --value "your,new,urls,here" \
  --type String \
  --overwrite \
  --region us-east-2
```

Similarly updating the TRMNL webhook URL is a SecureString parameter:

```shell
aws ssm put-parameter \
  --name /trmnl-calendar/webhook-url \
  --value "https://trmnl.com/api/custom_plugins/your-plugin-uuid-here" \
  --type SecureString \
  --region us-east-2
```
