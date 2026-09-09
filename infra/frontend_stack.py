"""Independent AWS frontend stack. Render with Python; deploy with CloudFormation.

No public S3 website, no credentials in JavaScript, no API caching or global
403/404-to-200 conversion. Existing backend stacks and records are not managed here.
"""
from __future__ import annotations

import argparse
import json

DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"
EXCEPT_HOST = "b689b0a8-53d0-40ab-baf2-68738e2966ac"

# Only application navigations are rewritten. A missing JS file remains an error.
SPA_CODE = """function handler(event) {
  var r = event.request;
  if (r.method !== 'GET' && r.method !== 'HEAD') return r;
  if (r.uri === '/' || /^\\/(overview|workspace|scenes|actions|approvals|turnovers|history|offers|allocations|pickups|documents|arrangements|receipts|settings|help|demo)(\\/[^.]*)?\\/?$/.test(r.uri)) {
    r.uri = '/index.html';
  }
  return r;
}"""


def ref(name):
    return {"Ref": name}


def sub(value):
    return {"Fn::Sub": value}


def attr(name, key):
    return {"Fn::GetAtt": [name, key]}


def template(product, repository, api_domain=""):
    if product not in {"lasttake", "merismos", "archon"}:
        raise ValueError("unknown product")
    if not repository.startswith("upgradedev/") or ":" in repository:
        raise ValueError("unexpected GitHub repository")
    common = {
        "ViewerProtocolPolicy": "redirect-to-https",
        "Compress": True,
        "ResponseHeadersPolicyId": ref("Headers"),
    }
    api = {
        **common, "TargetOriginId": "api",
        "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"],
        "CachedMethods": ["GET", "HEAD"],
        "CachePolicyId": DISABLED, "OriginRequestPolicyId": EXCEPT_HOST,
    }
    paths = ["/api/*", "/api", "/healthz"]
    if product == "merismos":
        paths += ["/offer/*", "/config", "/identity"]
    resources = {
        "Site": {
            "Type": "AWS::S3::Bucket", "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "Properties": {
                "BucketName": sub(product + "-web-${AWS::AccountId}-${AWS::Region}"),
                "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True, "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
                },
                "VersioningConfiguration": {"Status": "Enabled"},
                "BucketEncryption": {"ServerSideEncryptionConfiguration": [
                    {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]},
                "Tags": [{"Key": "project", "Value": product}, {"Key": "purpose", "Value": "agentsforhumans-frontend"}],
            },
        },
        "Access": {
            "Type": "AWS::CloudFront::OriginAccessControl",
            "Properties": {"OriginAccessControlConfig": {
                "Name": sub(product + "-web-${AWS::AccountId}"),
                "OriginAccessControlOriginType": "s3",
                "SigningBehavior": "always", "SigningProtocol": "sigv4",
            }},
        },
        "Router": {
            "Type": "AWS::CloudFront::Function",
            "Properties": {
                "Name": sub(product + "-web-router-${AWS::AccountId}"),
                "AutoPublish": True, "FunctionCode": SPA_CODE,
                "FunctionConfig": {"Comment": "Rewrite application paths only; API and missing assets stay errors", "Runtime": "cloudfront-js-2.0"},
            },
        },
        "Headers": {
            "Type": "AWS::CloudFront::ResponseHeadersPolicy",
            "Properties": {"ResponseHeadersPolicyConfig": {
                "Name": sub(product + "-web-headers-${AWS::AccountId}"),
                "SecurityHeadersConfig": {
                    "ContentTypeOptions": {"Override": True},
                    "FrameOptions": {"FrameOption": "DENY", "Override": True},
                    "ReferrerPolicy": {"ReferrerPolicy": "no-referrer", "Override": True},
                    "StrictTransportSecurity": {"AccessControlMaxAgeSec": 31536000, "IncludeSubdomains": True, "Override": True},
                    "ContentSecurityPolicy": {
                        "ContentSecurityPolicy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
                        "Override": True,
                    },
                },
                "CustomHeadersConfig": {"Items": [
                    {"Header": "Permissions-Policy", "Value": "camera=(), microphone=(), geolocation=()", "Override": True}
                ]},
            }},
        },
        "Distribution": {
            "Type": "AWS::CloudFront::Distribution",
            "Properties": {
                "DistributionConfig": {
                    "Comment": product + " Agents for Humans application frontend",
                    "Enabled": True, "HttpVersion": "http2and3",
                    "IPV6Enabled": True, "PriceClass": "PriceClass_100",
                    "DefaultRootObject": "index.html",
                    "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
                    "Origins": [
                        {"Id": "site", "DomainName": attr("Site", "RegionalDomainName"),
                         "S3OriginConfig": {"OriginAccessIdentity": ""},
                         "OriginAccessControlId": ref("Access")},
                        {"Id": "api", "DomainName": ref("ApiDomain"),
                         "CustomOriginConfig": {"OriginProtocolPolicy": "https-only",
                                                "OriginSSLProtocols": ["TLSv1.2"],
                                                "OriginReadTimeout": 30}},
                    ],
                    "DefaultCacheBehavior": {
                        **common, "TargetOriginId": "site",
                        "AllowedMethods": ["GET", "HEAD"], "CachedMethods": ["GET", "HEAD"],
                        "CachePolicyId": DISABLED,
                        "FunctionAssociations": [{"EventType": "viewer-request", "FunctionARN": attr("Router", "FunctionARN")}],
                    },
                    "CacheBehaviors": [
                        *[dict(api, PathPattern=path) for path in paths],
                        {**common, "PathPattern": "/assets/*", "TargetOriginId": "site",
                         "AllowedMethods": ["GET", "HEAD"], "CachedMethods": ["GET", "HEAD"],
                         "CachePolicyId": OPTIMIZED},
                    ],
                },
                "Tags": [{"Key": "project", "Value": product}],
            },
        },
        "SitePolicy": {
            "Type": "AWS::S3::BucketPolicy",
            "Properties": {"Bucket": ref("Site"), "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {"Sid": "OnlyOurCloudFrontReads", "Effect": "Allow",
                     "Principal": {"Service": "cloudfront.amazonaws.com"},
                     "Action": "s3:GetObject", "Resource": sub("${Site.Arn}/*"),
                     "Condition": {"StringEquals": {"AWS:SourceArn": sub("arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${Distribution}")}}},
                    {"Sid": "DenyPlainHttp", "Effect": "Deny", "Principal": "*",
                     "Action": "s3:*", "Resource": [attr("Site", "Arn"), sub("${Site.Arn}/*")],
                     "Condition": {"Bool": {"aws:SecureTransport": "false"}}},
                ],
            }},
        },
        "ReleaseRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "RoleName": product + "-frontend-release",
                "MaxSessionDuration": 3600,
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17", "Statement": [{
                        "Effect": "Allow", "Action": "sts:AssumeRoleWithWebIdentity",
                        "Principal": {"Federated": sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:oidc-provider/token.actions.githubusercontent.com")},
                        "Condition": {"StringEquals": {
                            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                            "token.actions.githubusercontent.com:sub": sub("${GitHubSubjectPrefix}:ref:refs/heads/main"),
                        }},
                    }],
                },
                "Policies": [{"PolicyName": "release-own-frontend-only", "PolicyDocument": {
                    "Version": "2012-10-17", "Statement": [
                        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"],
                         "Resource": sub("${Site.Arn}/*")},
                        {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:ListBucketVersions"],
                         "Resource": attr("Site", "Arn")},
                        {"Effect": "Allow", "Action": ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"],
                         "Resource": sub("arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${Distribution}")},
                        {"Effect": "Allow", "Action": "cloudformation:DescribeStacks",
                         "Resource": ref("AWS::StackId")},
                    ],
                }}],
            },
        },
    }
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": product + " React frontend: private S3, CloudFront OAC, same-origin uncached API, main-only OIDC release.",
        "Parameters": {"GitHubSubjectPrefix": {
            "Type": "String",
            "AllowedPattern": "repo:[A-Za-z0-9_.@/-]+",
            "Description": "Read sub_claim_prefix from gh api repos/OWNER/REPO/actions/oidc/customization/sub. Do not guess: new repositories use immutable numeric IDs.",
        }, "ApiDomain": {
            "Type": "String", "Default": api_domain,
            "AllowedPattern": "[a-z0-9]+\\.execute-api\\.[a-z0-9-]+\\.amazonaws\\.com",
            "Description": "Existing HTTP API domain without scheme, slash, or stage.",
        }},
        "Resources": resources,
        "Outputs": {
            "FrontendUrl": {"Value": sub("https://${Distribution.DomainName}/")},
            "FrontendBucket": {"Value": ref("Site")},
            "DistributionId": {"Value": ref("Distribution")},
            "ReleaseRoleArn": {"Value": attr("ReleaseRole", "Arn")},
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", required=True, choices=["lasttake", "merismos", "archon"])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--api-domain", default="")
    args = parser.parse_args()
    print(json.dumps(template(args.product, args.repository, args.api_domain), indent=2))
