package com.example.groceryshoppingapp

import android.os.Bundle
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.models.GenericResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ForgotPasswordActivity : AppCompatActivity() {

    private lateinit var emailEdit: EditText
    private lateinit var otpEdit: EditText
    private lateinit var passwordEdit: EditText
    private lateinit var actionButton: Button
    private lateinit var infoText: TextView

    private var step = 1  // 1=Send OTP, 2=Verify OTP, 3=Update Password

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_forgot_password)

        emailEdit = findViewById(R.id.et_email)
        otpEdit = findViewById(R.id.et_otp)
        passwordEdit = findViewById(R.id.et_new_password)
        actionButton = findViewById(R.id.btn_action)
        infoText = findViewById(R.id.tv_info)

        // Initially hide OTP and password fields
        otpEdit.visibility = View.GONE
        passwordEdit.visibility = View.GONE

        actionButton.setOnClickListener {
            when (step) {
                1 -> sendOtp()
                2 -> verifyOtp()
                3 -> updatePassword()
            }
        }
    }

    private fun sendOtp() {
        val email = emailEdit.text.toString().trim()
        if (email.isEmpty()) {
            infoText.text = "Please enter your email"
            return
        }

        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.sendPasswordResetOtp(mapOf("email" to email)).enqueue(object : Callback<GenericResponse> {
            override fun onResponse(call: Call<GenericResponse>, response: Response<GenericResponse>) {
                if (response.isSuccessful && response.body()?.success == true) {
                    infoText.text = "OTP sent to $email"
                    step = 2
                    otpEdit.visibility = View.VISIBLE
                    actionButton.text = "Verify OTP"
                } else {
                    infoText.text = response.body()?.message ?: "Failed to send OTP"
                }
            }

            override fun onFailure(call: Call<GenericResponse>, t: Throwable) {
                infoText.text = "Error: ${t.localizedMessage}"
            }
        })
    }

    private fun verifyOtp() {
        val email = emailEdit.text.toString().trim()
        val otp = otpEdit.text.toString().trim()
        if (otp.isEmpty()) {
            infoText.text = "Please enter OTP"
            return
        }

        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.verifyPasswordResetOtp(mapOf("email" to email, "otp" to otp)).enqueue(object : Callback<GenericResponse> {
            override fun onResponse(call: Call<GenericResponse>, response: Response<GenericResponse>) {
                if (response.isSuccessful && response.body()?.success == true) {
                    infoText.text = "OTP verified! Enter new password"
                    step = 3
                    passwordEdit.visibility = View.VISIBLE
                    actionButton.text = "Update Password"
                } else {
                    infoText.text = response.body()?.message ?: "Invalid OTP"
                }
            }

            override fun onFailure(call: Call<GenericResponse>, t: Throwable) {
                infoText.text = "Error: ${t.localizedMessage}"
            }
        })
    }

    private fun updatePassword() {
        val email = emailEdit.text.toString().trim()
        val newPassword = passwordEdit.text.toString().trim()
        if (newPassword.isEmpty()) {
            infoText.text = "Please enter new password"
            return
        }

        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        api.updatePassword(mapOf("email" to email, "password" to newPassword)).enqueue(object : Callback<GenericResponse> {
            override fun onResponse(call: Call<GenericResponse>, response: Response<GenericResponse>) {
                if (response.isSuccessful && response.body()?.success == true) {
                    Toast.makeText(this@ForgotPasswordActivity, "Password updated successfully", Toast.LENGTH_LONG).show()
                    finish() // Back to login
                } else {
                    infoText.text = response.body()?.message ?: "Failed to update password"
                }
            }

            override fun onFailure(call: Call<GenericResponse>, t: Throwable) {
                infoText.text = "Error: ${t.localizedMessage}"
            }
        })
    }
}
