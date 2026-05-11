$login = Read-Host "Have you already run 'az login'? (y/n)"

if ($login.ToLower() -ne 'y') {
    az login | Out-Null
}

$policy = "/providers/microsoft.management/managementgroups/mg-shc-test/providers/microsoft.authorization/policyassignments/407ae8cd77f04f32827c0170"
# NLP Exemptions at sub/RG scope
$Exemptions = @(
    @{
        SubscriptionId      = "54b323b0-e4e0-4692-adec-a4c4dc33fbc7"
        ResourceGroupName   = "rg-JLB-dev-Credentialing-Local"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "54b323b0-e4e0-4692-adec-a4c4dc33fbc7"
        ResourceGroupName   = "rg-JLB-dev-ELMER-Client-Credentialing-Common"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "54b323b0-e4e0-4692-adec-a4c4dc33fbc7"
        ResourceGroupName   = "rg-JLB-dev-ELMER-Client-Credentialing-Evaluations"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "54b323b0-e4e0-4692-adec-a4c4dc33fbc7"
        ResourceGroupName   = "rg-JLB-dev-ELMER-Client-Credentialing-Requirements"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "54b323b0-e4e0-4692-adec-a4c4dc33fbc7"
        ResourceGroupName   = "rg-JLB-Dev-ELMER-Client-Credentialing-Terraform"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "24b5efbb-f6e2-4552-8fea-bfbbae97c64a"
        ResourceGroupName   = "rg-JLB-prod-ELMER-Client-Credentialing-Common"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "24b5efbb-f6e2-4552-8fea-bfbbae97c64a"
        ResourceGroupName   = "rg-JLB-prod-ELMER-Client-Credentialing-Evaluations"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "24b5efbb-f6e2-4552-8fea-bfbbae97c64a"
        ResourceGroupName   = "rg-JLB-prod-ELMER-Client-Credentialing-Requirements"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "24b5efbb-f6e2-4552-8fea-bfbbae97c64a"
        ResourceGroupName   = "rg-JLB-prod-Elmer-Client-Credentialing-Terraform"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "c3d4e5f6-3333-4000-8000-333333333333"
        ResourceGroupName   = "rg-JLB-prod-Elmer-Client-Credentialing-Terraform"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "c3d4e5f6-3333-4000-8000-333333333333"
        ResourceGroupName   = "rg-JLB-test-ELMER-Client-Credentialing-Common"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "c3d4e5f6-3333-4000-8000-333333333333"
        ResourceGroupName   = "rg-JLB-test-ELMER-Client-Credentialing-Evaluations"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "c3d4e5f6-3333-4000-8000-333333333333"
        ResourceGroupName   = "rg-JLB-test-ELMER-Client-Credentialing-Requirements"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    },
    @{
        SubscriptionId      = "c3d4e5f6-3333-4000-8000-333333333333"
        ResourceGroupName   = "rg-JLB-test-Elmer-Client-Credentialing-Terraform"
        PolicyAssignmentId  = $policy
        Description         = "Waiver for NLP"
    }
)

$exemptionCategory = "Waiver"


foreach ($ex in $Exemptions){
  az account set --subscription $ex.SubscriptionId

  $scope = "/subscriptions/$($ex.SubscriptionId)/resourceGroups/$($ex.ResourceGroupName)"

  $name = "test-$($ex.ResourceGroupName)"

  if ($name.Length -gt 64) {
    $name = $name.Substring(0, 64)
}

  az policy exemption create --name $name --scope $scope --policy-assignment $ex.PolicyAssignmentId --display-name $name --description $ex.Description --exemption-category $exemptionCategory
  
}