// Where an owner whose sign-up isn't finished belongs (features/onboarding.py):
// "company" → step 2, "plan" → step 3. null once the trial has started, and
// for every other role.
export const onboardingPath = (user) => {
  if (user?.role !== 'business_owner') return null;
  if (user.onboarding_status === 'company') return '/onboarding/entreprise';
  if (user.onboarding_status === 'plan') return '/onboarding/formule';
  return null;
};
