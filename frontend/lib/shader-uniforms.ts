/**
 * Uniform type predicates for the WebGL shader renderer.
 *
 * These live in their own module (rather than inside `react-shader-toy.tsx`) so
 * they can be unit-tested without a DOM or a WebGL context.
 */

export type Vector4<T = number> = [T, T, T, T];

export type UniformValue = number[] | number;

export function isMatrixType(type: string, value: UniformValue): value is number[] {
  return type.includes('Matrix') && Array.isArray(value);
}

/**
 * Array uniforms (`2fv`, `3iv`, ...): the value must hold *more than one* vector
 * for the GLSL declaration to need an array size (`vec3[2]`). A single vector is
 * not a list, so this deliberately uses `>` rather than `>=`.
 */
export function isVectorListType(type: string, value: UniformValue): value is number[] {
  return (
    type.includes('v') && Array.isArray(value) && value.length > Number.parseInt(type.charAt(0), 10)
  );
}

/**
 * Single vector uniforms (`2f`, `3f`, `4f`): a value whose length *equals* the
 * component count is valid. Comparing with `>` (the previous behaviour) rejected
 * exactly the well-formed case, so the uniform was never uploaded and the shader
 * silently rendered with zeros.
 */
export function isVectorType(type: string, value: UniformValue): value is Vector4 {
  return (
    !type.includes('v') &&
    Array.isArray(value) &&
    value.length >= Number.parseInt(type.charAt(0), 10)
  );
}
