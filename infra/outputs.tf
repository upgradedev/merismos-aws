output "reader_url" {
  description = "The reader's Function URL. Public Function URLs were refused at account level on 2026-09-02, so this does not answer a stranger; the public path is CloudFront to the API in judge_url."
  value       = aws_lambda_function_url.reader.function_url
}

output "check_the_boundary" {
  description = "Commands against the Function URLs. Public Function URLs were refused at account level on 2026-09-02, so the reader's is refused too; the evaluator and writer URLs also require AWS_IAM."
  value = {
    identity  = "curl -s ${aws_lambda_function_url.reader.function_url}identity"
    catalog   = "curl -s ${aws_lambda_function_url.reader.function_url}catalog"
    evaluator = "curl -s -o /dev/null -w '%%{http_code}\n' ${aws_lambda_function_url.private["evaluator"].function_url}identity"
    writer    = "curl -s -o /dev/null -w '%%{http_code}\n' ${aws_lambda_function_url.private["writer"].function_url}identity"
  }
}

output "published_records" {
  description = "Where a published record lands. Readable with no account."
  value       = "https://${aws_s3_bucket.records.bucket_regional_domain_name}/records/"
}

# In this table, reads_publish_secret is about the boundary canary, which the
# publish path never reads, and answers_a_stranger describes the Function URLs
# as designed: in this account public Function URLs are refused, so the reader's
# answers 403 as well. The values are left as they are, because editing them
# adds an output change to the plan.
output "the_boundary_in_one_table" {
  description = "What each identity holds. /identity proves it live rather than asserting it."
  value = {
    for r in sort(tolist(local.roles)) : r => {
      role_arn             = aws_iam_role.fleet[r].arn
      may_publish          = r == "writer"
      reads_publish_secret = r == "writer" ? "granted" : "explicitly denied"
      answers_a_stranger   = r == "reader" ? "yes, 200" : "no, 403"
    }
  }
}

# The value still says the secret is retained for 7 days. Its recovery window
# is 0 days (main.tf), so it is not. The value is left as is, because editing
# it adds an output change to the plan.
output "teardown" {
  description = "What removing this fleet costs. The secret's recovery window is 0 days, so it does not outlast a destroy; dependency layer versions do."
  value       = "terraform destroy -auto-approve. The secret is retained for 7 days unless forced."
}

output "judge_url" {
  description = "The API Gateway endpoint. A judge opens the CloudFront site, which forwards API paths here, and this endpoint also answers directly. Rate limited, and it cannot publish without a person."
  value       = aws_apigatewayv2_api.judge.api_endpoint
}
