package com.example.groceryshoppingapp

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.models.LoginRequest
import com.example.groceryshoppingapp.models.LoginResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class LoginActivity : AppCompatActivity() {

    private lateinit var usernameEdit: EditText
    private lateinit var passwordEdit: EditText
    private lateinit var loginButton: Button
    private lateinit var registerText: TextView
    private lateinit var titleText: TextView
    private lateinit var errorText: TextView

    private val appRole by lazy { BuildConfig.APP_ROLE.lowercase() }

    override fun onCreate(savedInstanceState: Bundle?) {
        LanguageManager.applySavedLanguage(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        titleText = findViewById(R.id.tv_login_title)
        usernameEdit = findViewById(R.id.et_username)
        passwordEdit = findViewById(R.id.et_password)
        loginButton = findViewById(R.id.btn_login)
        registerText = findViewById(R.id.tv_register)
        errorText = findViewById(R.id.tv_error_message)

        titleText.text = when (appRole) {
            "customer" -> getString(R.string.customer_login)
            "shopowner" -> getString(R.string.shop_owner_login)
            else -> getString(R.string.login)
        }

        loginButton.setOnClickListener {
            val username = usernameEdit.text.toString().trim()
            val password = passwordEdit.text.toString().trim()
            errorText.visibility = View.GONE

            if (username.isEmpty() || password.isEmpty()) {
                errorText.text = getString(R.string.enter_username_password)
                errorText.visibility = View.VISIBLE
                return@setOnClickListener
            }

            doLogin(username, password)
        }

        registerText.setOnClickListener {
            startActivity(Intent(this, RegisterActivity::class.java))
        }
    }

    private fun doLogin(username: String, password: String) {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        api.login(LoginRequest(username, password)).enqueue(object : Callback<LoginResponse> {
            @SuppressLint("StringFormatInvalid")
            override fun onResponse(call: Call<LoginResponse>, response: Response<LoginResponse>) {
                Log.d("LoginDebug", "Raw response: ${response.body()} error=${response.errorBody()?.string()}")

                val loginResponse = response.body()
                if (response.isSuccessful && loginResponse?.success == true) {
                    val user = loginResponse.user
                    val loginRole = user?.role?.lowercase()?.trim()

                    // ✅ Save auth token immediately
                    loginResponse.token?.let { token ->
                        SessionManager.setAuthToken(this@LoginActivity, token)
                        Log.d("LoginDebug", "✅ Saved token=$token")
                    }

                    // Block login if role mismatch
                    if (loginRole != appRole) {
                        errorText.text = getString(R.string.role_mismatch, appRole.replaceFirstChar { it.uppercase() })
                        errorText.visibility = View.VISIBLE
                        return
                    }

                    // Save profile/session
                    SessionManager.saveLogin(this@LoginActivity, user?.username ?: "", loginRole ?: "")
                    SessionManager.saveUserProfile(
                        this@LoginActivity,
                        user?.fullName ?: "",
                        user?.address ?: "",
                        user?.phone ?: "",
                        user?.email ?: "",
                        user?.location ?: "",
                        user?.photoBase64 ?: ""
                    )
                    user?.customerId?.let { SessionManager.setCustomerId(this@LoginActivity, it) }
                    user?.shopkeeperId?.let { SessionManager.setShopkeeperId(this@LoginActivity, it) }

                    // ✅ Save shop info if existsg
                    if (user?.shop != null) {
                        //SessionManager.setShopId(this@LoginActivity, shop!!.id)   // ✅ keep UUID
                        //SessionManager.setShopInfo(this@LoginActivity, shop.id, shop.name)
                        // Make sure to store Firestore docId, not UUID
                        val shopDocId = user.shop?.id   // now guaranteed to be Firestore docId
                        if (!shopDocId.isNullOrEmpty()) {
                            SessionManager.setShopId(this@LoginActivity, shopDocId)
                            SessionManager.setShopInfo(this@LoginActivity, shopDocId, user.shop?.name ?: "")
                        }


                        // If backend did not send hasItems, but shop exists → assume true
                        val hasItems = user.hasItems ?: true
                        SessionManager.setHasItemsAdded(this@LoginActivity, hasItems)
                    }

                    // Redirect based on role and shop/items
                    when (loginRole) {
                        "customer" -> startActivity(Intent(this@LoginActivity, CustomerHomeActivity::class.java))
                        "shopowner" -> {
                            if (SessionManager.hasShopWithItems(this@LoginActivity)) {
                                startActivity(Intent(this@LoginActivity, ShopOwnerDashboardActivity::class.java))
                            } else {
                                startActivity(Intent(this@LoginActivity, AddItemsActivity::class.java))
                            }
                        }
                        else -> {
                            errorText.text = getString(R.string.unknown_user_role)
                            errorText.visibility = View.VISIBLE
                            return
                        }
                    }
                    finish()
                } else {
                    errorText.text = getString(R.string.invalid_username_password)
                    errorText.visibility = View.VISIBLE
                }
            }

            override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
                errorText.text = "Login failed: ${t.localizedMessage ?: "Unknown error"}"
                errorText.visibility = View.VISIBLE
            }
        })
    }
}
