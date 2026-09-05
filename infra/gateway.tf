###############################################################################
# The judge path.
#
# Lambda Function URLs are refused in the deploying account. That was not a
# configuration mistake: the URL's AuthType really is NONE, the resource policy
# really does allow lambda:InvokeFunctionUrl to everyone, there are no service
# control policies, no resource control policies and no declarative policies in
# the organisation, and it is the management account anyway. A throwaway Lambda
# with a two line handler and a public URL was also refused, which is what
# settled it. docs/deploy-2026-09-02.md has the whole elimination.
#
# So the reader is fronted by an HTTP API instead. Everything below except the
# integration exists to make an open endpoint survivable: this URL has to stay
# up until 2026-10-08 and it costs money every time somebody hits it.
#
# ONE LIMIT, AND HOW IT IS LIVED WITH. An HTTP API integration times out at 30
# seconds and that ceiling cannot be raised. A specialist reading with Claude
# Opus 5 takes about 100 seconds, so a chore cannot be awaited inside a request.
#
# It is not awaited. Pressing the button starts the chore on a background
# invocation of the reader, which has its own 900 second budget, and the page
# polls the provenance thread. The first deployment did run the deterministic
# rules synchronously, and a review caught what that cost: with the SDK removed
# the deployed path still worked, so the strongest claim in the entry was true
# of the repository and false of the demonstration.
###############################################################################

resource "aws_apigatewayv2_api" "judge" {
  name          = "${var.project}-judge"
  protocol_type = "HTTP"
  description   = "The one URL a judge opens. Rate limited, and it cannot publish."

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_integration" "reader" {
  api_id                 = aws_apigatewayv2_api.judge.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fleet["reader"].invoke_arn
  payload_format_version = "2.0"

  # The hard ceiling, and it cannot be raised on an HTTP API. It is why a chore
  # is started rather than awaited: no page here waits on a model.
  timeout_milliseconds = 30000
}

resource "aws_apigatewayv2_route" "everything" {
  api_id    = aws_apigatewayv2_api.judge.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.reader.id}"
}

resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.judge.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.reader.id}"
}

resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/aws/apigateway/${var.project}-judge"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "live" {
  api_id      = aws_apigatewayv2_api.judge.id
  name        = "$default"
  auto_deploy = true

  # An open endpoint with no ceiling is an open endpoint somebody else can
  # spend your money through. These are deliberately low: this serves a handful
  # of judges reading a few pages, not a product launch.
  default_route_settings {
    throttling_rate_limit    = var.judge_rate_limit
    throttling_burst_limit   = var.judge_burst_limit
    detailed_metrics_enabled = true
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.gateway.arn
    format = jsonencode({
      requestId = "$context.requestId"
      ip        = "$context.identity.sourceIp"
      method    = "$context.httpMethod"
      path      = "$context.path"
      status    = "$context.status"
      latency   = "$context.responseLatency"
      error     = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_lambda_permission" "gateway_may_invoke_the_reader" {
  statement_id  = "AllowJudgeGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fleet["reader"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.judge.execution_arn}/*/*"
}

###############################################################################
# Cost controls. The throttle above bounds requests per second; these bound
# what a sustained problem can cost before anybody notices.
###############################################################################

# A hard ceiling on how many readers can run at once. Without this, a burst
# through the gateway becomes an unbounded number of concurrent Lambdas, each
# of which may call Bedrock.
resource "aws_lambda_function_event_invoke_config" "reader_retries" {
  function_name          = aws_lambda_function.fleet["reader"].function_name
  maximum_retry_attempts = 0
}

resource "aws_cloudwatch_metric_alarm" "reader_errors" {
  alarm_name          = "${var.project}-reader-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_description   = "The judge path is failing. Five errors in five minutes."
  dimensions          = { FunctionName = aws_lambda_function.fleet["reader"].function_name }
}

resource "aws_cloudwatch_metric_alarm" "reader_volume" {
  alarm_name          = "${var.project}-reader-unexpected-volume"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Invocations"
  namespace           = "AWS/Lambda"
  period              = 3600
  statistic           = "Sum"
  threshold           = var.judge_hourly_alarm
  treat_missing_data  = "notBreaching"
  alarm_description   = "More traffic in an hour than a judging panel would produce. Check for a loop or a scraper."
  dimensions          = { FunctionName = aws_lambda_function.fleet["reader"].function_name }
}
