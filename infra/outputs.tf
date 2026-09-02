output "reader_url" {
  description = "The one URL a judge opens. Answers a stranger, by design."
  value       = aws_lambda_function_url.reader.function_url
}

output "check_the_boundary" {
  description = "Three commands a stranger can run. The first answers, the other two are refused by IAM."
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

output "teardown" {
  description = "What removing this fleet costs. Nothing here survives a destroy except the secret's recovery window."
  value       = "terraform destroy -auto-approve. The secret is retained for 7 days unless forced."
}
